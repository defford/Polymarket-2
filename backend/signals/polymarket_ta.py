"""
Layer 1 Signal: Technical Analysis on Polymarket token prices.

Analyzes the "Up" token price movements on Polymarket itself.
If the Up token RSI is climbing / MACD crossing up → sentiment shifting bullish.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from models import Layer1Signal
from config import SignalConfig

logger = logging.getLogger(__name__)


def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI manually (no ta-lib dependency needed)."""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(
    prices: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD, Signal line, and Histogram."""
    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_layer1_signal(
    price_history: list[dict],
    config: SignalConfig,
) -> Layer1Signal:
    """
    Compute Layer 1 signal from Polymarket token price history.

    Args:
        price_history: List of {timestamp, price} dicts from CLOB price history
                       (for the "Up" token)
        config: Signal configuration parameters

    Returns:
        Layer1Signal with direction (-1 to +1) and confidence (0 to 1)
    """
    if not price_history or len(price_history) < max(config.pm_macd_slow, config.pm_rsi_period) + 5:
        logger.debug(f"Not enough price history for Layer 1 ({len(price_history)} points)")
        return Layer1Signal()

    # Build DataFrame from price history
    try:
        df = pd.DataFrame(price_history)
        if "p" in df.columns:
            df.rename(columns={"p": "price", "t": "timestamp"}, inplace=True)
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["price"])

        if len(df) < config.pm_rsi_period + 5:
            return Layer1Signal()

        prices = df["price"]
    except Exception as e:
        logger.error(f"Error building Layer 1 DataFrame: {e}")
        return Layer1Signal()

    # --- RSI ---
    rsi_series = calculate_rsi(prices, config.pm_rsi_period)
    current_rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50.0

    rsi_signal = 0.0
    rsi_valid = True
    if not np.isnan(current_rsi):
        if current_rsi < 5 or current_rsi > 95:
            logger.debug(f"RSI out of valid range: {current_rsi:.1f}, treating as invalid")
            rsi_valid = False
            rsi_signal = 0.0
        elif current_rsi < 15:
            rsi_signal = (15 - current_rsi) / 15
        elif current_rsi > config.pm_rsi_overbought:
            rsi_signal = -(current_rsi - config.pm_rsi_overbought) / (100 - config.pm_rsi_overbought)
        else:
            rsi_signal = 0.0

    # --- MACD ---
    macd_line, signal_line, histogram = calculate_macd(
        prices, config.pm_macd_fast, config.pm_macd_slow, config.pm_macd_signal
    )
    current_macd = macd_line.iloc[-1] if not macd_line.empty else 0.0
    current_signal = signal_line.iloc[-1] if not signal_line.empty else 0.0
    current_hist = histogram.iloc[-1] if not histogram.empty else 0.0
    prev_hist = histogram.iloc[-2] if len(histogram) > 1 else 0.0

    macd_signal = 0.0
    if not np.isnan(current_hist):
        # Histogram direction and acceleration
        if current_hist > 0 and current_hist > prev_hist:
            macd_signal = min(1.0, abs(current_hist) * 20)  # Bullish and accelerating
        elif current_hist < 0 and current_hist < prev_hist:
            macd_signal = -min(1.0, abs(current_hist) * 20)  # Bearish and accelerating
        elif current_hist > 0:
            macd_signal = 0.3  # Bullish but decelerating
        elif current_hist < 0:
            macd_signal = -0.3  # Bearish but decelerating

    # --- Momentum ---
    lookback = min(config.pm_momentum_lookback, len(prices) - 1)
    if lookback > 0:
        momentum = (prices.iloc[-1] - prices.iloc[-1 - lookback]) / max(prices.iloc[-1 - lookback], 0.001)
        momentum_signal = np.clip(momentum * 10, -1.0, 1.0)  # Scale to [-1, 1]
    else:
        momentum = 0.0
        momentum_signal = 0.0

    # --- Combine sub-signals ---
    # Weight: RSI 35%, MACD 40%, Momentum 25%
    direction = np.clip(
        0.35 * rsi_signal + 0.40 * macd_signal + 0.25 * momentum_signal,
        -1.0,
        1.0,
    )

    # Confidence based on signal agreement
    signals = [rsi_signal, macd_signal, momentum_signal]
    same_direction = all(s >= 0 for s in signals) or all(s <= 0 for s in signals)
    avg_magnitude = np.mean([abs(s) for s in signals])

    confidence = avg_magnitude
    if same_direction:
        confidence = min(1.0, confidence * 1.3)  # Boost when all agree
    else:
        confidence *= 0.7  # Reduce when conflicting

    # Penalize confidence if RSI was invalid (extreme values)
    if not rsi_valid:
        confidence *= 0.6
        logger.debug(f"Layer 1 confidence reduced due to invalid RSI: {confidence:.2f}")

    return Layer1Signal(
        rsi=float(current_rsi) if not np.isnan(current_rsi) else None,
        macd=float(current_macd) if not np.isnan(current_macd) else None,
        macd_signal_line=float(current_signal) if not np.isnan(current_signal) else None,
        macd_histogram=float(current_hist) if not np.isnan(current_hist) else None,
        momentum=float(momentum),
        direction=float(direction),
        confidence=float(np.clip(confidence, 0.0, 1.0)),
    )
