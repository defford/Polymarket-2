"""
Layer 2 Signal: BTC Price Multi-Timeframe EMA Analysis.

Analyzes actual BTC/USDT price across 6 timeframes (1m to 1d).
Each timeframe votes bullish/bearish based on EMA crossovers.
More alignment across timeframes → higher conviction.

TUNED FOR 15-MINUTE BINARY MARKETS:
- Short timeframes (1m/5m/15m) weighted heavily — they matter most
- Confidence based primarily on ALIGNMENT count, not direction magnitude
- Higher TFs serve as trend filter / tiebreaker, not primary signal
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from models import Layer2Signal
from config import SignalConfig

logger = logging.getLogger(__name__)


def compute_ema_signal(df: pd.DataFrame, ema_periods: list[int]) -> float:
    """
    Compute directional signal from EMA crossovers for a single timeframe.

    Returns: float between -1.0 and +1.0
    """
    if df is None or df.empty or len(df) < max(ema_periods) + 1:
        return 0.0

    close = df["close"]
    current_price = close.iloc[-1]

    # Calculate EMAs
    emas = {}
    for period in sorted(ema_periods):
        ema = close.ewm(span=period, adjust=False).mean()
        emas[period] = ema.iloc[-1]

    if not emas:
        return 0.0

    # Signal component 1: Price position relative to EMAs
    above_count = sum(1 for v in emas.values() if current_price > v)
    total = len(emas)
    position_signal = (above_count / total) * 2 - 1  # Map to [-1, 1]

    # Signal component 2: EMA ordering (shorter above longer = bullish)
    sorted_periods = sorted(emas.keys())
    if len(sorted_periods) >= 2:
        ordering_score = 0.0
        pairs = 0
        for i in range(len(sorted_periods)):
            for j in range(i + 1, len(sorted_periods)):
                short_ema = emas[sorted_periods[i]]
                long_ema = emas[sorted_periods[j]]
                if short_ema > long_ema:
                    ordering_score += 1
                else:
                    ordering_score -= 1
                pairs += 1
        ordering_signal = ordering_score / pairs if pairs > 0 else 0.0
    else:
        ordering_signal = 0.0

    # Signal component 3: Recent price momentum (last 3 candles)
    if len(close) >= 4:
        recent_change = (close.iloc[-1] - close.iloc[-4]) / close.iloc[-4]
        momentum_signal = np.clip(recent_change * 50, -1.0, 1.0)
    else:
        momentum_signal = 0.0

    # Combine: position 40%, ordering 35%, momentum 25%
    combined = 0.40 * position_signal + 0.35 * ordering_signal + 0.25 * momentum_signal
    return float(np.clip(combined, -1.0, 1.0))


def compute_short_term_pressure(
    candles: dict[str, pd.DataFrame],
    config: SignalConfig,
) -> dict:
    """
    Compute short-term BTC pressure from 1m/5m/15m only.
    Used by the exit strategy to scale stop losses.
    
    Returns dict with:
        - pressure: float from -1.0 (strongly bearish) to +1.0 (strongly bullish)
        - momentum: float, raw short-term momentum
        - alignment: int, how many of 3 short TFs agree
        - details: dict of per-timeframe signals
    """
    short_tfs = {
        "1m": (config.btc_ema_1m, 0.45),   # heaviest weight — most immediate
        "5m": (config.btc_ema_5m, 0.35),
        "15m": (config.btc_ema_15m, 0.20),  # lightest — still somewhat lagging
    }

    signals = {}
    weighted_sum = 0.0
    total_weight = 0.0
    bullish = 0
    bearish = 0

    for tf, (ema_periods, weight) in short_tfs.items():
        df = candles.get(tf)
        if df is None or df.empty:
            continue

        sig = compute_ema_signal(df, ema_periods)
        signals[tf] = sig

        weighted_sum += sig * weight
        total_weight += weight

        if sig > 0.1:
            bullish += 1
        elif sig < -0.1:
            bearish += 1

    if total_weight == 0:
        return {"pressure": 0.0, "momentum": 0.0, "alignment": 0, "details": {}}

    pressure = weighted_sum / total_weight

    # Raw momentum from 1m candles (most sensitive)
    momentum = 0.0
    df_1m = candles.get("1m")
    if df_1m is not None and len(df_1m) >= 4:
        close = df_1m["close"]
        # Price change over last 3 candles (3 minutes)
        pct_change = (close.iloc[-1] - close.iloc[-4]) / close.iloc[-4]
        momentum = float(np.clip(pct_change * 100, -1.0, 1.0))

    alignment = max(bullish, bearish)

    return {
        "pressure": float(np.clip(pressure, -1.0, 1.0)),
        "momentum": momentum,
        "alignment": alignment,
        "total": len(signals),
        "details": signals,
    }


def compute_layer2_signal(
    candles: dict[str, pd.DataFrame],
    config: SignalConfig,
) -> Layer2Signal:
    """
    Compute Layer 2 signal from multi-timeframe BTC candle data.
    """
    # Map timeframes to their EMA period configs
    tf_ema_map = {
        "1m": config.btc_ema_1m,
        "5m": config.btc_ema_5m,
        "15m": config.btc_ema_15m,
        "1h": config.btc_ema_1h,
        "4h": config.btc_ema_4h,
        "1d": config.btc_ema_1d,
    }

    # ─── REBALANCED WEIGHTS: 15m & 1h dominate ───
    # We prioritize the trend on the 15m and 1h charts.
    # If these two don't align, we shouldn't trade.
    tf_weights = {
        "1m": 0.10,
        "5m": 0.15,
        "15m": 0.35,  # Primary trend for 15m binary options
        "1h": 0.30,   # Macro trend confirmation
        "4h": 0.05,
        "1d": 0.05,
    }

    timeframe_signals = {}
    weighted_sum = 0.0
    total_weight = 0.0
    bullish_count = 0
    bearish_count = 0
    total_computed = 0

    for tf, ema_periods in tf_ema_map.items():
        df = candles.get(tf)
        if df is None or df.empty:
            continue

        signal = compute_ema_signal(df, ema_periods)
        timeframe_signals[tf] = signal

        weight = tf_weights.get(tf, 0.1)
        weighted_sum += signal * weight
        total_weight += weight
        total_computed += 1

        if signal > 0.1:
            bullish_count += 1
        elif signal < -0.1:
            bearish_count += 1

    if total_weight == 0:
        return Layer2Signal()

    # Overall direction (weighted average)
    direction = weighted_sum / total_weight

    # ─── CRITICAL CHECK: 15m and 1h Alignment ───
    # If the 15m or 1h timeframe strongly disagrees with the trade direction, 
    # kill the signal (confidence = 0).
    sig_15m = timeframe_signals.get("15m", 0.0)
    sig_1h = timeframe_signals.get("1h", 0.0)
    
    # We check if they are "fighting" the direction.
    # E.g. direction is UP (>0), but 15m is DOWN (<-0.1) -> KILL
    # We use a small buffer (0.1) to ignore neutral/weak signals.
    fighting_trend = False
    
    if direction > 0.1:  # Bullish signal
        if sig_15m < -0.1 or sig_1h < -0.1:
            fighting_trend = True
    elif direction < -0.1:  # Bearish signal
        if sig_15m > 0.1 or sig_1h > 0.1:
            fighting_trend = True

    # Alignment: how many timeframes agree
    alignment = max(bullish_count, bearish_count)

    # ─── FIXED CONFIDENCE: Based primarily on alignment ratio ───
    if total_computed > 0:
        alignment_ratio = alignment / total_computed

        # Base confidence from alignment alone
        # 3/6 = 0.30, 4/6 = 0.55, 5/6 = 0.80, 6/6 = 1.0
        if alignment_ratio >= 0.8:        # 5+ of 6
            base_confidence = 0.80
        elif alignment_ratio >= 0.67:     # 4 of 6
            base_confidence = 0.55
        elif alignment_ratio >= 0.5:      # 3 of 6
            base_confidence = 0.30
        else:
            base_confidence = 0.10

        # Direction magnitude adds a bonus (up to +0.20)
        direction_bonus = min(0.20, abs(direction) * 0.5)
        
        confidence = min(1.0, base_confidence + direction_bonus)
    else:
        confidence = 0.0

    # If fighting the 15m/1h trend, kill confidence
    if fighting_trend:
        logger.info(f"Layer 2 Signal VETOED: Fighting 15m/1h trend (Dir:{direction:.2f}, 15m:{sig_15m:.2f}, 1h:{sig_1h:.2f})")
        confidence = 0.0
        direction = 0.0 # Force neutral

    return Layer2Signal(
        timeframe_signals=timeframe_signals,
        alignment_count=alignment,
        total_timeframes=total_computed,
        direction=float(np.clip(direction, -1.0, 1.0)),
        confidence=float(np.clip(confidence, 0.0, 1.0)),
    )


def compute_atr(df: pd.DataFrame, period: int = 14) -> dict:
    """
    Compute Average True Range (ATR) for volatility measurement.
    
    ATR measures market volatility by decomposing the entire range of price movement.
    For 15-minute binary markets, ATR helps identify:
    - High-noise environments where stops are more likely to be triggered
    - Low-volatility conditions where price movement may be insufficient
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ATR smoothing period (default 14)
    
    Returns:
        dict with:
            - atr_value: Raw ATR in price units
            - atr_percent: ATR as percentage of current price
            - atr_normalized_bps: ATR in basis points
            - volatility_regime: 'low', 'medium', 'high', or 'extreme'
            - true_range_latest: Most recent True Range value
    """
    if df is None or df.empty or len(df) < period + 1:
        return {
            "atr_value": None,
            "atr_percent": None,
            "atr_normalized_bps": None,
            "volatility_regime": None,
            "true_range_latest": None,
        }
    
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    if len(high) < 2:
        return {
            "atr_value": None,
            "atr_percent": None,
            "atr_normalized_bps": None,
            "volatility_regime": None,
            "true_range_latest": None,
        }
    
    # Calculate True Range
    # TR = max(high - low, |high - prev_close|, |low - prev_close|)
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR is EMA of True Range
    atr_series = true_range.ewm(alpha=1/period, adjust=False).mean()
    atr_value = atr_series.iloc[-1]
    
    current_price = close.iloc[-1]
    
    # ATR as percentage of price
    atr_percent = atr_value / current_price if current_price > 0 else 0
    
    # ATR in basis points
    atr_bps = atr_percent * 10000
    
    # Classify volatility regime based on ATR percentile
    # Using historical ATR distribution to classify
    atr_history = atr_series.dropna().tail(100)  # Last 100 periods
    if len(atr_history) >= 20:
        pct_25 = atr_history.quantile(0.25)
        pct_50 = atr_history.quantile(0.50)
        pct_75 = atr_history.quantile(0.75)
        
        if atr_value <= pct_25:
            regime = "low"
        elif atr_value <= pct_50:
            regime = "medium"
        elif atr_value <= pct_75:
            regime = "high"
        else:
            regime = "extreme"
    else:
        # Fallback: use fixed percentages
        if atr_percent < 0.002:  # < 0.2%
            regime = "low"
        elif atr_percent < 0.004:  # < 0.4%
            regime = "medium"
        elif atr_percent < 0.006:  # < 0.6%
            regime = "high"
        else:
            regime = "extreme"
    
    return {
        "atr_value": float(atr_value),
        "atr_percent": float(atr_percent),
        "atr_normalized_bps": float(atr_bps),
        "volatility_regime": regime,
        "true_range_latest": float(true_range.iloc[-1]),
    }


def compute_atr_15m(df: pd.DataFrame, period: int = 14, reference_window: int = 100) -> dict:
    """
    Compute 15m ATR specifically for delta scaling (TP adjustment).
    
    This is separate from the 1m ATR used for general volatility classification.
    The 15m ATR is more appropriate for scaling take-profit levels in 15-minute
    binary markets, as it captures the expected price range within the market window.
    
    Args:
        df: DataFrame with 15m candles (high, low, close)
        period: ATR smoothing period (default 14)
        reference_window: Number of periods for percentile calculation
    
    Returns:
        dict with:
            - atr_15m_value: Raw ATR in price units
            - atr_15m_bps: ATR in basis points
            - atr_15m_percentile: Percentile rank (0-100) vs historical
            - atr_zscore: Z-score vs historical mean
    """
    if df is None or df.empty or len(df) < period + 1:
        return {
            "atr_15m_value": None,
            "atr_15m_bps": None,
            "atr_15m_percentile": None,
            "atr_zscore": None,
        }
    
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    if len(high) < 2:
        return {
            "atr_15m_value": None,
            "atr_15m_bps": None,
            "atr_15m_percentile": None,
            "atr_zscore": None,
        }
    
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr_series = true_range.ewm(alpha=1/period, adjust=False).mean()
    atr_value = atr_series.iloc[-1]
    
    current_price = close.iloc[-1]
    atr_percent = atr_value / current_price if current_price > 0 else 0
    atr_bps = atr_percent * 10000
    
    atr_history = atr_series.dropna().tail(reference_window)
    if len(atr_history) >= 20:
        percentile = (atr_history < atr_value).sum() / len(atr_history) * 100
        mean_atr = atr_history.mean()
        std_atr = atr_history.std()
        zscore = (atr_value - mean_atr) / std_atr if std_atr > 0 else 0
    else:
        percentile = 50.0
        zscore = 0.0
    
    return {
        "atr_15m_value": float(atr_value),
        "atr_15m_bps": float(atr_bps),
        "atr_15m_percentile": float(percentile),
        "atr_zscore": float(zscore),
    }
