"""
VWAP (Volume Weighted Average Price) and VROC (Volume Rate of Change).

Both indicators are ALWAYS computed regardless of toggle state so that
their values appear in signal logs for data collection.  The toggle
controls whether they influence trading decisions.

VWAP
----
Session-bounded average price weighted by volume.  Produces a directional
signal based on where current price sits relative to VWAP and its
standard-deviation bands (z-score).

VROC
----
Percentage change in volume relative to recent average.  Used as a
confidence gate: low VROC during a breakout signal suggests a fakeout.
"""

import logging
from datetime import timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_vwap(df_1m: pd.DataFrame, session_reset_hour_utc: int = 0) -> dict:
    """
    Compute VWAP from 1-minute candles for the current session.

    Args:
        df_1m: DataFrame with columns [timestamp, open, high, low, close, volume].
        session_reset_hour_utc: Hour (0-23) at which the VWAP session resets.

    Returns:
        Dictionary with VWAP data and a directional signal in [-1, +1].
    """
    empty = {
        "vwap": None,
        "price": None,
        "upper_1": None,
        "lower_1": None,
        "upper_2": None,
        "lower_2": None,
        "std_dev": None,
        "band_position": 0.0,
        "signal": 0.0,
    }

    if df_1m is None or df_1m.empty or len(df_1m) < 5:
        return empty

    try:
        # Session boundary: keep only candles from after the last reset hour
        now_utc = pd.Timestamp.now(tz="UTC")
        session_start = now_utc.normalize().replace(hour=session_reset_hour_utc)
        if session_start > now_utc:
            # Reset hour hasn't happened yet today — use yesterday's
            session_start -= pd.Timedelta(days=1)

        session_df = df_1m[df_1m["timestamp"] >= session_start].copy()

        if session_df.empty or len(session_df) < 5:
            return empty

        typical_price = (
            session_df["high"] + session_df["low"] + session_df["close"]
        ) / 3
        volume = session_df["volume"]

        # Avoid division by zero when volume is all zeros
        cumulative_vol = volume.cumsum()
        if cumulative_vol.iloc[-1] == 0:
            return empty

        cumulative_tp_vol = (typical_price * volume).cumsum()
        vwap_series = cumulative_tp_vol / cumulative_vol

        current_vwap = float(vwap_series.iloc[-1])
        current_price = float(session_df["close"].iloc[-1])

        # Standard deviation bands (volume-weighted)
        squared_diff = ((typical_price - vwap_series) ** 2 * volume).cumsum()
        variance = squared_diff / cumulative_vol
        std_dev = float(np.sqrt(variance.iloc[-1]))

        # Band position (z-score): how many std devs price is from VWAP
        if std_dev > 0:
            band_position = (current_price - current_vwap) / std_dev
        else:
            band_position = 0.0

        # Directional signal: above VWAP = bullish, below = bearish
        # Scale z-score to [-1, +1] — ±2σ maps to ±1.0
        signal = float(np.clip(band_position / 2.0, -1.0, 1.0))

        return {
            "vwap": current_vwap,
            "price": current_price,
            "upper_1": current_vwap + std_dev,
            "lower_1": current_vwap - std_dev,
            "upper_2": current_vwap + 2 * std_dev,
            "lower_2": current_vwap - 2 * std_dev,
            "std_dev": std_dev,
            "band_position": float(band_position),
            "signal": signal,
        }

    except Exception as e:
        logger.error(f"VWAP computation error: {e}")
        return empty


def compute_vroc(df_15m: pd.DataFrame, lookback: int = 10) -> dict:
    """
    Compute Volume Rate of Change from 15-minute candles.

    VROC = ((current_volume − avg_volume_over_N) / avg_volume_over_N) × 100

    A VROC spike of 50%+ during a structural break suggests institutional
    participation; low VROC during a breakout suggests a fakeout.

    Args:
        df_15m: DataFrame with at least a 'volume' column.
        lookback: Number of prior candles for the average.

    Returns:
        Dictionary with VROC data.
    """
    empty = {"vroc": 0.0, "current_volume": 0.0, "avg_volume": 0.0}

    if df_15m is None or df_15m.empty or len(df_15m) < lookback + 1:
        return empty

    try:
        current_vol = float(df_15m["volume"].iloc[-1])
        # Average of the *previous* N candles (exclude current)
        avg_vol = float(df_15m["volume"].iloc[-(lookback + 1) : -1].mean())

        if avg_vol > 0:
            vroc = ((current_vol - avg_vol) / avg_vol) * 100.0
        else:
            vroc = 0.0

        return {
            "vroc": float(vroc),
            "current_volume": current_vol,
            "avg_volume": avg_vol,
        }

    except Exception as e:
        logger.error(f"VROC computation error: {e}")
        return empty
