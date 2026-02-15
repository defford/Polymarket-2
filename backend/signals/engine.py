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
from signals.vwap_vroc import compute_vwap, compute_vroc
from polymarket.client import polymarket_client
from binance.client import binance_client
from bayesian_manager import bin_l1_evidence, bin_l2_evidence

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

        # --- Fetch BTC candles once (reused by Layer 2, VWAP, VROC) ---
        candles = self._fetch_candles()

        # --- Layer 2: BTC Multi-TF EMAs ---
        layer2 = self._compute_layer2(config, candles)

        # --- VWAP: always computed for data collection ---
        vwap_data = compute_vwap(
            candles.get("1m"),
            session_reset_hour_utc=config.vwap_session_reset_hour_utc,
        )

        # --- VROC: always computed for data collection ---
        vroc_data = compute_vroc(
            candles.get("15m"),
            lookback=config.vroc_lookback,
        )

        # --- Combine ---
        composite = self._combine_signals(layer1, layer2, config, vwap_data, vroc_data)

        self._last_signal = composite

        # Prepare safe values for logging
        l1_rsi = layer1.rsi if layer1.rsi is not None else 50.0
        l1_macd = layer1.macd if layer1.macd is not None else 0.0
        l1_hist = layer1.macd_histogram if layer1.macd_histogram is not None else 0.0

        comp_conf = getattr(composite, 'composite_confidence', 0.0)
        comp_conf = comp_conf if comp_conf is not None else 0.0

        vwap_str = f"{vwap_data['vwap']:.2f}" if vwap_data.get("vwap") else "N/A"
        vwap_tag = "ON" if config.vwap_enabled else "off"
        vroc_tag = "ON" if config.vroc_enabled else "off"

        logger.info(
            f"SIGNAL ANALYSIS:\n"
            f"  Layer 1 (Polymarket): {layer1.direction:+.3f} (Conf: {layer1.confidence:.2f})\n"
            f"    - RSI: {l1_rsi:.1f} | MACD: {l1_macd:.4f} | Hist: {l1_hist:.4f}\n"
            f"  Layer 2 (Bitcoin):    {layer2.direction:+.3f} (Conf: {layer2.confidence:.2f})\n"
            f"    - Alignment: {layer2.alignment_count}/{layer2.total_timeframes}\n"
            f"  VWAP [{vwap_tag}]: {vwap_str} | signal={vwap_data['signal']:+.3f} | z={vwap_data['band_position']:+.2f}\n"
            f"  VROC [{vroc_tag}]: {vroc_data['vroc']:+.1f}% | confirmed={composite.vroc_confirmed}\n"
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

    def _fetch_candles(self) -> dict:
        """Fetch BTC candles once for reuse across Layer 2, VWAP, and VROC."""
        try:
            return self._btc_client.fetch_all_timeframes()
        except Exception as e:
            logger.error(f"Error fetching BTC candles: {e}")
            return {}

    def _compute_layer2(self, config, candles: dict) -> Layer2Signal:
        """Compute Layer 2 from pre-fetched BTC candles."""
        try:
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
        vwap_data: dict,
        vroc_data: dict,
    ) -> CompositeSignal:
        """
        Combine both layers into a composite signal.

        KEY DESIGN: Use direction scores DIRECTLY with weights.
        Don't multiply direction x confidence — that double-penalizes
        weak-but-valid signals. Confidence is used as a GATE, not a multiplier.

        VWAP (when enabled): blended into composite score as a third directional
        component.  Weights (L1 + L2 + VWAP) are normalised to 1.0.

        VROC (when enabled): acts as a confidence gate.  If the current candle's
        volume rate of change is below the threshold, composite confidence is
        penalised, making it harder to pass the min_signal_confidence gate.
        """

        l1_weight = config.layer1_weight
        l2_weight = config.layer2_weight

        # ─── VWAP: optional third directional component ───
        vwap_signal = vwap_data.get("signal", 0.0)
        vwap_weight = config.vwap_weight if config.vwap_enabled else 0.0

        # Normalize weights (L1 + L2 + optional VWAP)
        total_weight = l1_weight + l2_weight + vwap_weight
        if total_weight > 0:
            l1_weight /= total_weight
            l2_weight /= total_weight
            vwap_weight /= total_weight

        # If both core layers have no data at all, bail
        if layer1.confidence == 0 and layer2.confidence == 0:
            return CompositeSignal(
                layer1=layer1,
                layer2=layer2,
                composite_score=0.0,
                composite_confidence=0.0,
                should_trade=False,
                timestamp=datetime.now(timezone.utc),
                vwap_enabled=config.vwap_enabled,
                vwap_value=vwap_data.get("vwap"),
                vwap_signal=vwap_signal,
                vwap_band_position=vwap_data.get("band_position", 0.0),
                vroc_enabled=config.vroc_enabled,
                vroc_value=vwap_data.get("vroc", 0.0),
                vroc_confirmed=True,
                l1_evidence=bin_l1_evidence(layer1.direction),
                l2_evidence=bin_l2_evidence(layer2.direction),
            )

        # If one core layer has zero confidence, redistribute its weight
        if layer1.confidence == 0:
            remaining = l1_weight
            l1_weight = 0
            # Redistribute proportionally to L2 and VWAP
            if l2_weight + vwap_weight > 0:
                ratio = remaining / (l2_weight + vwap_weight)
                l2_weight += l2_weight * ratio
                vwap_weight += vwap_weight * ratio
            else:
                l2_weight = 1.0
        elif layer2.confidence == 0:
            remaining = l2_weight
            l2_weight = 0
            if l1_weight + vwap_weight > 0:
                ratio = remaining / (l1_weight + vwap_weight)
                l1_weight += l1_weight * ratio
                vwap_weight += vwap_weight * ratio
            else:
                l1_weight = 1.0

        # ─── Composite score: weighted average of DIRECTIONS ───
        composite_score = (
            l1_weight * layer1.direction
            + l2_weight * layer2.direction
            + vwap_weight * vwap_signal
        )

        # ─── Composite confidence: weighted average (core layers only) ───
        # VWAP doesn't have its own "confidence" — it's always available when
        # candle data is present, so it only contributes to direction.
        core_weight = l1_weight + l2_weight
        if core_weight > 0:
            composite_confidence = (
                l1_weight * layer1.confidence + l2_weight * layer2.confidence
            ) / core_weight
        else:
            composite_confidence = 0.0

        # Bonus: if both core layers agree on direction, boost confidence
        if layer1.direction != 0 and layer2.direction != 0:
            same_direction = (layer1.direction > 0) == (layer2.direction > 0)
            if same_direction:
                composite_confidence = min(1.0, composite_confidence * 1.4)

        # ─── VROC: confidence gate (when enabled) ───
        vroc_pct = vroc_data.get("vroc", 0.0)
        vroc_confirmed = vroc_pct >= config.vroc_threshold

        if config.vroc_enabled and not vroc_confirmed:
            # Volume doesn't confirm the move — penalise confidence
            composite_confidence *= config.vroc_confidence_penalty

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
            # VWAP data (always populated for data collection)
            vwap_enabled=config.vwap_enabled,
            vwap_value=vwap_data.get("vwap"),
            vwap_signal=vwap_signal,
            vwap_band_position=vwap_data.get("band_position", 0.0),
            # VROC data (always populated for data collection)
            vroc_enabled=config.vroc_enabled,
            vroc_value=vroc_pct,
            vroc_confirmed=vroc_confirmed,
            # Bayesian evidence categories
            l1_evidence=bin_l1_evidence(layer1.direction),
            l2_evidence=bin_l2_evidence(layer2.direction),
        )


# Global singleton
signal_engine = SignalEngine()
