# Bot Configuration & Logic Guide

This document explains every parameter in `bot_config.json` and how it influences the bot's decision-making process.

## 1. Signal Configuration (`"signal"`)

These parameters control how the bot generates buy/sell signals by analyzing both Polymarket token data (Layer 1) and Bitcoin price action (Layer 2).

### Layer 1: Polymarket Technical Analysis
The bot analyzes the price history of the specific outcome token (e.g., "Will BTC hit 100k?").

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pm_rsi_period` | `14` | Lookback period for RSI (Relative Strength Index). Measures if the token is overbought/oversold. |
| `pm_rsi_oversold` | `30` | RSI level below which the token is considered "oversold" (Bullish signal). |
| `pm_rsi_overbought` | `70` | RSI level above which the token is considered "overbought" (Bearish signal). |
| `pm_macd_fast` | `12` | Fast EMA period for MACD (Moving Average Convergence Divergence). |
| `pm_macd_slow` | `26` | Slow EMA period for MACD. |
| `pm_macd_signal` | `9` | Signal line period for MACD. Positive histogram = Bullish; Negative = Bearish. |
| `pm_momentum_lookback`| `5` | Number of previous price points to compare for simple momentum (Rate of Change). |

**How Layer 1 Score is Calculated (Internal Logic):**
*   **RSI**: +0.5 (Bullish) / -0.5 (Bearish) if outside bounds. +/- 0.1 for trends.
*   **MACD**: +0.5/-0.5 based on histogram. Bonus +/- 0.2 if above/below zero line.
*   **Momentum**: +/- 0.3 if change > 1%.
*   *Result is normalized to -1.0 to +1.0.*

### Layer 2: Bitcoin Technical Analysis
The bot analyzes BTC/USDT price action on Binance to predict general market sentiment, which correlates with many Polymarket crypto markets.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `btc_ema_1m` | `[5, 13]` | EMA periods to check on the 1-minute chart. |
| `btc_ema_5m` | `[8, 21]` | EMA periods to check on the 5-minute chart. |
| `btc_ema_15m` | `[9, 21, 55]`| EMA periods to check on the 15-minute chart. **Critical for trend.** |
| `btc_ema_1h` | `[12, 26]` | EMA periods to check on the 1-hour chart. **Critical for trend.** |
| `btc_ema_4h` | `[20, 50]` | EMA periods to check on the 4-hour chart. |
| `btc_ema_1d` | `[20, 50, 200]`| EMA periods to check on the daily chart. |

**How Layer 2 Score is Calculated (Internal Logic):**
The bot calculates a weighted average of signals from all timeframes. The internal weights (hardcoded in `btc_ta.py`) favor the 15m and 1h charts for binary option trading:
*   **15m**: 35% weight
*   **1h**: 30% weight
*   **5m**: 15% weight
*   **1m**: 10% weight
*   **4h/1d**: 5% each
*   *VETO RULE*: If the 15m or 1h signal strongly contradicts the overall direction, the Layer 2 confidence is set to 0 (No Trade).

### Signal Combination

| Parameter | Default | Description |
|-----------|---------|-------------|
| `layer1_weight` | `0.75` | Importance of the Polymarket Token analysis. Higher = trust the token price action more. |
| `layer2_weight` | `0.3` | Importance of the Bitcoin analysis. Higher = trust the macro BTC trend more. |
| `buy_threshold` | `0.3` | The **Composite Score** must exceed this value (positive or negative) to trigger a trade. |

*Note: `layer1_weight` and `layer2_weight` are normalized. If L1=0.75 and L2=0.3, the actual split is ~71% L1 and ~29% L2.*

---

## 2. Risk Management (`"risk"`)

These parameters act as a safety gate. Even if a signal is strong, the Risk Manager can block the trade.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_size` | `5` | Maximum amount (in USD) to risk on a single trade. |
| `max_trades_per_window`| `2` | Max number of trades allowed within a single 15-minute market window. |
| `max_daily_loss` | `20` | If the bot loses this amount (USD) in a day, it enters cooldown. |
| `min_signal_confidence`| `0.4` | (0.0 - 1.0). Minimum confidence level required to trade. This is separate from the score/direction. Confidence comes from indicators aligning. |
| `max_consecutive_losses`| `4` | Max allowed losses in a row before triggering a cooldown. |
| `cooldown_minutes` | `15` | How long to pause trading after hitting a loss limit. |
| `stop_trading_minutes...`| `2` | Stop entering new trades this many minutes before the market resolves. |
| `max_entry_price` | `0.8` | Do not buy if the token price is already above 80 cents (Risk/Reward is too poor). |

---

## 3. Exit Strategy (`"exit"`)

The bot monitors open positions and can exit early to lock profits or cut losses.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | `true` | Master switch for the exit module. |
| `trailing_stop_pct` | `0.2` | (20%). If price drops 20% from its **peak** since entry, sell. |
| `hard_stop_pct` | `0.5` | (50%). Absolute emergency stop. If price drops 50% from **entry**, sell immediately. |
| `signal_reversal_threshold`| `0.15`| If the bot's signal flips against you by this amount, exit. |
| `tighten_at_seconds` | `180` | When 3 minutes (180s) are left, switch to a tighter trailing stop. |
| `tightened_trailing_pct`| `0.1` | (10%). The tighter trailing stop used in the final minutes. |
| `final_seconds` | `60` | When 60 seconds are left, switch to the "Final" ultra-tight stop. |
| `final_trailing_pct` | `0.05` | (5%). The ultra-tight stop used in the last minute. |
| `min_hold_seconds` | `20` | Minimum time to hold a trade before allowing an early exit (prevents instant panic selling). |

### BTC Pressure Scaling
The bot dynamically adjusts the trailing stop based on short-term BTC moves (1m/5m charts).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pressure_scaling_enabled`| `true` | Enable dynamic stop-loss adjustment. |
| `pressure_widen_max` | `1.5` | If BTC moves **with** us, widen the stop by up to 1.5x (give it room). |
| `pressure_tighten_min` | `0.4` | If BTC moves **against** us, tighten the stop to 0.4x (cut it fast). |
| `pressure_neutral_zone` | `0.15` | Small BTC moves (noise) below this threshold are ignored. |

---

## 4. Trading Behavior (`"trading"`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `order_type` | `"postOnly"`| Default order type (`postOnly` saves fees/earns rebates). |
| `price_offset` | `0.01` | How much to undercut the best ask/bid when placing a limit order. |
| `use_fok_for_strong...`| `false` | If true, switch to Market/FOK orders for very strong signals to ensure entry. |
| `strong_signal_threshold`| `0.8` | Score required to trigger the FOK/Market order behavior. |
| `poll_interval_seconds` | `10` | How often the bot wakes up to check prices and signals. |
| `market_discovery...` | `30` | How often to scan for new/active markets. |
