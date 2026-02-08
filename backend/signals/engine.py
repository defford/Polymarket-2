"""
Signal Engine: Combines Layer 1 (Polymarket TA) and Layer 2 (BTC EMAs)
into a composite trading signal.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from models import CompositeSignal, Layer1Signal, Layer2Signal, Side, MarketInfo
from config import config_manager
from signals.polymarket_ta import compute_layer1_signal
from signals.btc_ta import compute_layer2_signal
from polymarket.client import polymarket_client
from binance.client import binance_client

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orchestrates signal generation from both layers and produces
    a composite trading signal.
    """

    def __init__(self, config_mgr=None, binance_cli=None, polymarket_cli=None):
        self._config_mgr = config_mgr  # None = use global
        self._binance_cli = binance_cli
        self._polymarket_cli = polymarket_cli
        self._last_signal: Optional[CompositeSignal] = None

    @property
    def _cfg(self):
        return self._config_mgr if self._config_mgr is not None else config_manager

    @property
    def _pm_client(self):
        return self._polymarket_cli if self._polymarket_cli is not None else polymarket_client

    @property
    def _btc_client(self):
        return self._binance_cli if self._binance_cli is not None else binance_client

    @property
    def last_signal(self) -> Optional[CompositeSignal]:
        return self._last_signal

    def compute_signal(self, market: MarketInfo) -> CompositeSignal:
        config = self._cfg.config.signal

        # --- Layer 1: Polymarket Token TA ---
        layer1 = self._compute_layer1(market, config)

        # --- Layer 2: BTC Multi-TF EMAs ---
        layer2 = self._compute_layer2(config)

        # --- Combine ---
        composite = self._combine_signals(layer1, layer2, config)

        self._last_signal = composite

        # Prepare safe values for logging
        l1_rsi = layer1.rsi if layer1.rsi is not None else 50.0
        l1_macd = layer1.macd if layer1.macd is not None else 0.0
        l1_hist = layer1.macd_histogram if layer1.macd_histogram is not None else 0.0
        
        comp_conf = getattr(composite, 'composite_confidence', 0.0)
        # Ensure comp_conf is a float even if getattr returns None (though model defines it as float)
        comp_conf = comp_conf if comp_conf is not None else 0.0

        logger.info(
            f"SIGNAL ANALYSIS:\n"
            f"  Layer 1 (Polymarket): {layer1.direction:+.3f} (Conf: {layer1.confidence:.2f})\n"
            f"    - RSI: {l1_rsi:.1f} | MACD: {l1_macd:.4f} | Hist: {l1_hist:.4f}\n"
            f"  Layer 2 (Bitcoin):    {layer2.direction:+.3f} (Conf: {layer2.confidence:.2f})\n"
            f"    - Alignment: {layer2.alignment_count}/{layer2.total_timeframes}\n"
            f"  COMPOSITE: {composite.composite_score:+.3f} (Conf: {comp_conf:.2f})\n"
            f"  ACTION: {'TRADE ' + composite.recommended_side.value.upper() if composite.should_trade else 'NO TRADE'}"
        )

        return composite

    def _compute_layer1(self, market: MarketInfo, config) -> Layer1Signal:
        """Fetch Polymarket price history and compute Layer 1."""
        try:
            # Use interval="max" to get full history for the active token
            # fidelity=10 implies 10-second resolution (sufficient for 15m markets)
            price_history = self._pm_client.get_price_history(
                token_id=market.up_token_id,
                interval="max",
                fidelity=10,
            )

            if price_history:
                return compute_layer1_signal(price_history, config)
            else:
                logger.debug("No Polymarket price history available for Layer 1")
                return Layer1Signal()

        except Exception as e:
            logger.error(f"Layer 1 computation error: {e}")
            return Layer1Signal()

    def _compute_layer2(self, config) -> Layer2Signal:
        """Fetch BTC candles and compute Layer 2."""
        try:
            candles = self._btc_client.fetch_all_timeframes()

            if candles:
                return compute_layer2_signal(candles, config)
            else:
                logger.debug("No BTC candle data available for Layer 2")
                return Layer2Signal()

        except Exception as e:
            logger.error(f"Layer 2 computation error: {e}")
            return Layer2Signal()

    def _combine_signals(
        self,
        layer1: Layer1Signal,
        layer2: Layer2Signal,
        config,
    ) -> CompositeSignal:
        """
        Combine both layers into a composite signal.
        
        KEY DESIGN: Use direction scores DIRECTLY with weights.
        Don't multiply direction × confidence — that double-penalizes 
        weak-but-valid signals. Confidence is used as a GATE, not a multiplier.
        """

        l1_weight = config.layer1_weight
        l2_weight = config.layer2_weight

        # Normalize weights
        total_weight = l1_weight + l2_weight
        if total_weight > 0:
            l1_weight /= total_weight
            l2_weight /= total_weight

        # If both layers have no data at all, bail
        if layer1.confidence == 0 and layer2.confidence == 0:
            return CompositeSignal(
                layer1=layer1,
                layer2=layer2,
                composite_score=0.0,
                composite_confidence=0.0,
                should_trade=False,
                timestamp=datetime.now(timezone.utc),
            )

        # If one layer has zero confidence, rely entirely on the other
        if layer1.confidence == 0:
            l1_weight = 0
            l2_weight = 1.0
        elif layer2.confidence == 0:
            l1_weight = 1.0
            l2_weight = 0

        # ─── Composite score: weighted average of DIRECTIONS ───
        # This preserves the actual signal strength
        composite_score = (
            l1_weight * layer1.direction
            + l2_weight * layer2.direction
        )

        # ─── Composite confidence: weighted average ───
        composite_confidence = (
            l1_weight * layer1.confidence + l2_weight * layer2.confidence
        )
        
        # Bonus: if both layers agree on direction, boost confidence
        if layer1.direction != 0 and layer2.direction != 0:
            same_direction = (layer1.direction > 0) == (layer2.direction > 0)
            if same_direction:
                composite_confidence = min(1.0, composite_confidence * 1.4)

        # Determine direction and whether to trade
        recommended_side = None
        should_trade = False

        if abs(composite_score) >= config.buy_threshold:
            if composite_score > 0:
                recommended_side = Side.UP
            else:
                recommended_side = Side.DOWN

            # Confidence gate
            min_conf = self._cfg.config.risk.min_signal_confidence
            if composite_confidence >= min_conf:
                should_trade = True

        return CompositeSignal(
            layer1=layer1,
            layer2=layer2,
            composite_score=float(np.clip(composite_score, -1.0, 1.0)),
            composite_confidence=float(np.clip(composite_confidence, 0.0, 1.0)),
            recommended_side=recommended_side,
            should_trade=should_trade,
            timestamp=datetime.now(timezone.utc),
        )


# Global singleton
signal_engine = SignalEngine()
