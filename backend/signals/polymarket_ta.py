"""
Layer 1: Polymarket Token Technical Analysis.

Analyzes the price history of the Polymarket outcome token itself.
While outcome tokens are not traditional assets, short-term momentum
and mean reversion patterns (RSI) still apply to order flow.
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict

from models import Layer1Signal

logger = logging.getLogger(__name__)


def compute_layer1_signal(price_history: List[Dict], config) -> Layer1Signal:
    """
    Compute Layer 1 signal based on token price history.
    
    Args:
        price_history: List of dicts [{'t': timestamp, 'p': price}, ...]
        config: SignalConfig object
        
    Returns:
        Layer1Signal with RSI, MACD, and directional scores.
    """
    if not price_history or len(price_history) < 30:
        return Layer1Signal()

    try:
        # Convert to DataFrame
        df = pd.DataFrame(price_history)
        
        # Ensure correct columns (API returns 't' and 'p')
        if 'p' not in df.columns:
            # Try to handle potential variations
            if 'price' in df.columns:
                df = df.rename(columns={'price': 'p'})
            else:
                logger.warning("Layer 1: 'p' column missing in price history")
                return Layer1Signal()
                
        # Sort by time just in case
        if 't' in df.columns:
            df = df.sort_values('t')
            
        prices = df['p'].astype(float)
        
        # --- 1. RSI (Relative Strength Index) ---
        rsi_period = config.pm_rsi_period
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        # --- 2. MACD (Moving Average Convergence Divergence) ---
        ema_fast = prices.ewm(span=config.pm_macd_fast, adjust=False).mean()
        ema_slow = prices.ewm(span=config.pm_macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=config.pm_macd_signal, adjust=False).mean()
        macd_hist = macd_line - signal_line
        
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        current_hist = macd_hist.iloc[-1]
        
        # --- 3. Momentum (Rate of Change) ---
        momentum_lookback = config.pm_momentum_lookback
        momentum = prices.pct_change(periods=momentum_lookback)
        current_momentum = momentum.iloc[-1]
        
        # --- Scoring Logic ---
        score = 0.0
        
        # RSI Score: Mean reversion logic
        # If RSI is low (<30), it's oversold -> Bullish (+1)
        # If RSI is high (>70), it's overbought -> Bearish (-1)
        # Polymarket tokens often trend, so extreme RSI might actually indicate strong momentum too.
        # However, for now, we'll stick to standard mean reversion or trend following?
        # Let's assume trend following for middle ranges and reversion for extremes?
        # Actually, standard RSI usage:
        # > 70 = Overbought (Sell/Down)
        # < 30 = Oversold (Buy/Up)
        
        if current_rsi > config.pm_rsi_overbought:
            score -= 0.5  # Bearish
        elif current_rsi < config.pm_rsi_oversold:
            score += 0.5  # Bullish
        else:
            # Neutral zone - slight trend following?
            if current_rsi > 55:
                score += 0.1
            elif current_rsi < 45:
                score -= 0.1
                
        # MACD Score: Trend following
        if current_hist > 0:
            score += 0.5
            if current_macd > 0: # Above zero line + positive hist = Strong Bullish
                score += 0.2
        else:
            score -= 0.5
            if current_macd < 0: # Below zero line + negative hist = Strong Bearish
                score -= 0.2
                
        # Momentum Score
        if current_momentum > 0.01: # > 1% move
            score += 0.3
        elif current_momentum < -0.01:
            score -= 0.3
            
        # Normalize Score to -1 to +1
        # Max possible roughly: 0.5 + 0.7 + 0.3 = 1.5
        normalized_direction = np.clip(score, -1.0, 1.0)
        
        # Confidence calculation
        # Higher confidence if indicators align
        confidence = 0.0
        
        # Basic alignment check
        rsi_bullish = current_rsi < 50
        macd_bullish = current_hist > 0
        mom_bullish = current_momentum > 0
        
        if rsi_bullish == macd_bullish:
            confidence += 0.3
        if macd_bullish == mom_bullish:
            confidence += 0.3
        
        # Extremes increase confidence (e.g. very oversold or strong momentum)
        if current_rsi < 20 or current_rsi > 80:
            confidence += 0.2
        if abs(current_momentum) > 0.05:
            confidence += 0.2
            
        confidence = np.clip(confidence, 0.1, 1.0)
        
        return Layer1Signal(
            rsi=float(current_rsi),
            macd=float(current_macd),
            macd_signal_line=float(current_signal),
            macd_histogram=float(current_hist),
            momentum=float(current_momentum),
            direction=float(normalized_direction),
            confidence=float(confidence)
        )
        
    except Exception as e:
        logger.error(f"Error computing Layer 1 signal: {e}")
        return Layer1Signal()
