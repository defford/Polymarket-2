"""
Signal Engine: Combines Layer 1 (Polymarket TA) and Layer 2 (BTC EMAs)
into a composite trading signal.

ASYNC version with:
- Async price history fetching
- Async candle fetching with parallel execution
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from models import CompositeSignal, Layer1Signal, Layer2Signal, Side, MarketInfo
from config import config_manager
from signals.polymarket_ta import compute_layer1_signal
from signals.btc_ta import compute_layer2_signal, compute_atr, compute_atr_15m
from signals.vwap_vroc import compute_vwap, compute_vroc
from polymarket.client import polymarket_client
from binance.client import binance_client
from bayesian_manager import bin_l1_evidence, bin_l2_evidence

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orchestrates signal generation from both layers and produces
    a composite trading signal.
    
    All I/O operations are async to avoid blocking the event loop.
    """

    def __init__(self, config_mgr=None, binance_cli=None, polymarket_cli=None):
        self._config_mgr = config_mgr
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

    async def compute_signal(self, market: MarketInfo) -> CompositeSignal:
        """
        Compute the composite trading signal.
        
        Fetches data in PARALLEL where possible:
        - Layer 1 (Polymarket price history) and BTC candles are fetched concurrently
        """
        config = self._cfg.config.signal
        start_time = time.time()

        layer1_task = asyncio.create_task(self._compute_layer1(market, config))
        candles_task = asyncio.create_task(self._fetch_candles())
        
        layer1, candles = await asyncio.gather(layer1_task, candles_task)

        layer2 = self._compute_layer2(config, candles)

        atr_data = compute_atr(candles.get("1m"), period=14)
        atr_15m_data = compute_atr_15m(candles.get("15m"), period=14)
        vwap_data = compute_vwap(
            candles.get("1m"),
            session_reset_hour_utc=config.vwap_session_reset_hour_utc,
        )
        vroc_data = compute_vroc(
            candles.get("15m"),
            lookback=config.vroc_lookback,
        )

        composite = self._combine_signals(layer1, layer2, config, vwap_data, vroc_data, atr_data, atr_15m_data)

        self._last_signal = composite

        l1_rsi = layer1.rsi if layer1.rsi is not None else 50.0
        l1_macd = layer1.macd if layer1.macd is not None else 0.0
        l1_hist = layer1.macd_histogram if layer1.macd_histogram is not None else 0.0

        comp_conf = getattr(composite, 'composite_confidence', 0.0)
        comp_conf = comp_conf if comp_conf is not None else 0.0

        vwap_str = f"{vwap_data['vwap']:.2f}" if vwap_data.get("vwap") else "N/A"
        vwap_tag = "ON" if config.vwap_enabled else "off"
        vroc_tag = "ON" if config.vroc_enabled else "off"
        atr_str = f"{atr_data['atr_normalized_bps']:.1f} bps" if atr_data.get("atr_value") else "N/A"

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"SIGNAL ANALYSIS ({elapsed_ms:.0f}ms):\n"
            f"  Layer 1 (Polymarket): {layer1.direction:+.3f} (Conf: {layer1.confidence:.2f})\n"
            f"    - RSI: {l1_rsi:.1f} | MACD: {l1_macd:.4f} | Hist: {l1_hist:.4f}\n"
            f"  Layer 2 (Bitcoin):    {layer2.direction:+.3f} (Conf: {layer2.confidence:.2f})\n"
            f"    - Alignment: {layer2.alignment_count}/{layer2.total_timeframes}\n"
            f"  VWAP [{vwap_tag}]: {vwap_str} | signal={vwap_data['signal']:+.3f} | z={vwap_data['band_position']:+.2f}\n"
            f"  VROC [{vroc_tag}]: {vroc_data['vroc']:+.1f}% | confirmed={composite.vroc_confirmed}\n"
            f"  ATR: {atr_str} | regime={atr_data.get('volatility_regime', 'N/A')}\n"
            f"  COMPOSITE: {composite.composite_score:+.3f} (Conf: {comp_conf:.2f})\n"
            f"  ACTION: {'TRADE ' + composite.recommended_side.value.upper() if composite.should_trade else 'NO TRADE'}"
        )

        return composite

    async def _compute_layer1(self, market: MarketInfo, config) -> Layer1Signal:
        """Fetch Polymarket price history and compute Layer 1 (async)."""
        try:
            price_history = await self._pm_client.get_price_history(
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

    async def _fetch_candles(self) -> dict:
        """Fetch BTC candles once for reuse across Layer 2, VWAP, and VROC (async)."""
        try:
            return await self._btc_client.fetch_all_timeframes()
        except Exception as e:
            logger.error(f"Error fetching BTC candles: {e}")
            return {}

    def _compute_layer2(self, config, candles: dict) -> Layer2Signal:
        """Compute Layer 2 from pre-fetched BTC candles (sync, CPU-bound)."""
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
        atr_data: dict,
        atr_15m_data: dict = None,
    ) -> CompositeSignal:
        """
        Combine both layers into a composite signal.
        """
        if atr_15m_data is None:
            atr_15m_data = {}

        l1_weight = config.layer1_weight
        l2_weight = config.layer2_weight

        vwap_signal = vwap_data.get("signal", 0.0)
        vwap_weight = config.vwap_weight if config.vwap_enabled else 0.0

        total_weight = l1_weight + l2_weight + vwap_weight
        if total_weight > 0:
            l1_weight /= total_weight
            l2_weight /= total_weight
            vwap_weight /= total_weight

        disagreement = self._analyze_layer_disagreement(
            layer1, layer2, vroc_data.get("vroc", 0.0), config.vroc_threshold, config
        )

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
                vroc_value=vroc_data.get("vroc", 0.0),
                vroc_confirmed=True,
                l1_evidence=bin_l1_evidence(layer1.direction),
                l2_evidence=bin_l2_evidence(layer2.direction),
                atr_value=atr_data.get("atr_value"),
                atr_percent=atr_data.get("atr_percent"),
                atr_normalized_bps=atr_data.get("atr_normalized_bps"),
                volatility_regime=atr_data.get("volatility_regime"),
                layer_disagreement=disagreement,
            )

        if layer1.confidence == 0:
            remaining = l1_weight
            l1_weight = 0
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

        composite_score = (
            l1_weight * layer1.direction
            + l2_weight * layer2.direction
            + vwap_weight * vwap_signal
        )

        core_weight = l1_weight + l2_weight
        if core_weight > 0:
            composite_confidence = (
                l1_weight * layer1.confidence + l2_weight * layer2.confidence
            ) / core_weight
        else:
            composite_confidence = 0.0

        if layer1.direction != 0 and layer2.direction != 0:
            same_direction = (layer1.direction > 0) == (layer2.direction > 0)
            if same_direction:
                composite_confidence = min(1.0, composite_confidence * 1.4)
            elif config.require_layer_agreement:
                composite_confidence *= 0.5
                logger.debug(
                    f"Layer disagreement penalty: L1={layer1.direction:+.2f}, "
                    f"L2={layer2.direction:+.2f}, confidence={composite_confidence:.2f}"
                )

        if layer2.alignment_count < config.min_l2_alignment:
            composite_confidence *= 0.5
            logger.debug(
                f"L2 alignment below threshold: {layer2.alignment_count}/{layer2.total_timeframes} "
                f"< {config.min_l2_alignment}, confidence={composite_confidence:.2f}"
            )

        vroc_pct = vroc_data.get("vroc", 0.0)
        vroc_confirmed = vroc_pct >= config.vroc_threshold

        if config.vroc_enabled and not vroc_confirmed:
            composite_confidence *= config.vroc_confidence_penalty

        recommended_side = None
        should_trade = False

        if abs(composite_score) >= config.buy_threshold:
            if composite_score > 0:
                recommended_side = Side.UP
            else:
                recommended_side = Side.DOWN

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
            vwap_enabled=config.vwap_enabled,
            vwap_value=vwap_data.get("vwap"),
            vwap_signal=vwap_signal,
            vwap_band_position=vwap_data.get("band_position", 0.0),
            vroc_enabled=config.vroc_enabled,
            vroc_value=vroc_pct,
            vroc_confirmed=vroc_confirmed,
            l1_evidence=bin_l1_evidence(layer1.direction),
            l2_evidence=bin_l2_evidence(layer2.direction),
            atr_value=atr_data.get("atr_value"),
            atr_percent=atr_data.get("atr_percent"),
            atr_normalized_bps=atr_data.get("atr_normalized_bps"),
            volatility_regime=atr_data.get("volatility_regime"),
            atr_15m_value=atr_15m_data.get("atr_15m_value"),
            atr_15m_bps=atr_15m_data.get("atr_15m_bps"),
            atr_15m_percentile=atr_15m_data.get("atr_15m_percentile"),
            layer_disagreement=disagreement,
        )

    def _analyze_layer_disagreement(
        self,
        layer1: Layer1Signal,
        layer2: Layer2Signal,
        vroc_value: float,
        vroc_threshold: float,
        config,
    ) -> dict:
        """
        When L1 and L2 disagree, identify which L2 component caused the conflict.
        """
        if not layer1.direction and not layer2.direction:
            return {"agreement": True, "reason": "both_neutral"}
        
        l1_direction = "bullish" if layer1.direction > 0.1 else "bearish" if layer1.direction < -0.1 else "neutral"
        l2_direction = "bullish" if layer2.direction > 0.1 else "bearish" if layer2.direction < -0.1 else "neutral"
        
        if l1_direction == "neutral" or l2_direction == "neutral":
            return {"agreement": True, "reason": "one_neutral", "l1_direction": l1_direction, "l2_direction": l2_direction}
        
        if l1_direction == l2_direction:
            return {"agreement": True, "l1_direction": l1_direction, "l2_direction": l2_direction}
        
        tf_weights = {
            "1m": 0.10,
            "5m": 0.15,
            "15m": 0.35,
            "1h": 0.30,
            "4h": 0.05,
            "1d": 0.05,
        }
        
        conflict_sources = []
        for tf, sig in layer2.timeframe_signals.items():
            tf_direction = "bullish" if sig > 0.1 else "bearish" if sig < -0.1 else "neutral"
            
            if tf_direction != "neutral" and tf_direction != l1_direction:
                conflict_sources.append({
                    "timeframe": tf,
                    "signal": round(sig, 4),
                    "conflicts_with": f"L1_{l1_direction}",
                    "weight": tf_weights.get(tf, 0.1),
                })
        
        dominant_conflict_tf = None
        if conflict_sources:
            dominant_conflict_tf = max(conflict_sources, key=lambda x: x["weight"])["timeframe"]
        
        vroc_conflict = vroc_value < vroc_threshold
        
        return {
            "agreement": False,
            "l1_direction": round(layer1.direction, 4),
            "l2_direction": round(layer2.direction, 4),
            "l1_direction_label": l1_direction,
            "l2_direction_label": l2_direction,
            "conflict_sources": conflict_sources,
            "dominant_conflict_tf": dominant_conflict_tf,
            "vroc_conflict": vroc_conflict,
            "vroc_value": round(vroc_value, 2),
            "vroc_threshold": vroc_threshold,
        }


signal_engine = SignalEngine()