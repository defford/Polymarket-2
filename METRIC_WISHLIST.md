# Trading Metric Wishlist

Future indicators and enhancements for the Polymarket BTC 15-minute trading bot.
Each metric is scored on two axes (1–10 scale):

- **Ease of Implementation** — How much work is needed given the existing codebase. Higher = easier.
- **Usefulness** — Expected impact on the bot's trading effectiveness. Higher = more useful.
- **Priority Score** — `(Ease + Usefulness) / 2`, weighted average for quick ranking.

Current signal stack for context:
- **Layer 1**: Polymarket token TA (RSI, MACD, Momentum) → `backend/signals/polymarket_ta.py`
- **Layer 2**: BTC multi-timeframe EMAs (1m → 1d) → `backend/signals/btc_ta.py`
- **Exits**: Trailing stop, hard stop, signal reversal, BTC pressure scaling → `backend/trading/exits.py`
- **Data**: Binance OHLCV candles (250 bars per timeframe, volume included) → `backend/binance/client.py`

---

## Scoring Summary

| # | Metric                              | Ease | Usefulness | Priority | Status  |
|---|-------------------------------------|------|------------|----------|---------|
| 1 | VWAP + Std Dev Bands                |  9   |     8      |   8.5    | Planned |
| 2 | VROC (Volume Rate of Change)        |  9   |     8      |   8.5    | Planned |
| 3 | ATR-Based Dynamic Stops             |  8   |     8      |   8.0    | Planned |
| 4 | Order Book Imbalance (OBI)          |  6   |     9      |   7.5    | Planned |
| 5 | Volume Profile (HVN & LVN)         |  5   |     7      |   6.0    | Planned |
| 6 | Regime-Aware Take Profit Scaling    |  4   |     9      |   6.5    | Planned |
| 7 | Multi-TF Trend Filter (EMA 20/50)  |  9   |     5      |   7.0    | Planned |

---

## 1. VWAP + Standard Deviation Bands

**Ease: 9/10 · Usefulness: 8/10 · Priority: 8.5**

### What it does
The Volume Weighted Average Price represents the true "fair value" for the current
session by weighting price by the volume traded at each level. Standard deviation
bands (±1σ, ±2σ) identify overextended moves.

### Why it matters for this bot
- A decisive BTC close above/below VWAP distinguishes structural breakouts from
  random noise — directly relevant to predicting the next 15-minute candle direction.
- The ±2σ band acts as a mean-reversion signal: if BTC is at +2σ, the probability
  of "Down" winning the next 15-min window increases.
- Combines naturally with the existing Layer 2 EMA signal as a confirmation filter.

### Implementation notes
- **Data available**: Binance candles already include OHLCV. VWAP is a running
  calculation: `cumsum(typical_price × volume) / cumsum(volume)` where
  `typical_price = (high + low + close) / 3`.
- **Where it fits**: New function in `backend/signals/btc_ta.py`, called alongside
  EMA computation. Could add a VWAP direction/deviation score to `Layer2Signal` or
  create a standalone signal component.
- **Config additions**: Session reset time (default: 00:00 UTC), deviation band
  multipliers.
- **Minimal dependencies**: Pure pandas/numpy — no new packages needed.

### Scoring rationale
- **Ease (9)**: Trivial math on data we already fetch. The Binance client provides
  volume with every candle. A single function computes VWAP and bands.
- **Usefulness (8)**: Strong institutional benchmark. VWAP crossovers are one of
  the most reliable intraday signals. Slightly below 9 because we trade binary
  options (direction only), so the absolute VWAP level matters less than its slope
  and crossover timing.

---

## 2. VROC (Volume Rate of Change)

**Ease: 9/10 · Usefulness: 8/10 · Priority: 8.5**

### What it does
Measures the percentage change in volume relative to its N-period average:
`VROC = ((current_volume - volume_N_ago) / volume_N_ago) × 100`. A spike of 50%+
signals that institutional "smart money" is participating in a move.

### Why it matters for this bot
- The bot's biggest risk is fakeout breakouts — low-liquidity moves that trigger
  entries but immediately reverse. VROC acts as a "conviction filter" for
  structural breaks.
- A VROC spike during a 15-minute candle opening validates that the EMA signal
  has institutional backing.
- Pairs naturally with the existing composite signal: only allow trades when
  `composite_score > threshold AND vroc > 50%`.

### Implementation notes
- **Calculation**: One line on the volume column of existing Binance candle data.
  `vroc = (df['volume'].iloc[-1] / df['volume'].rolling(N).mean().iloc[-1] - 1) * 100`
- **Where it fits**: Add to `backend/signals/btc_ta.py` as a volume confirmation
  score. Could be integrated into `compute_layer2_signal()` or used as a gate in
  `backend/signals/engine.py`.
- **Config additions**: `vroc_lookback` (default: 10 periods), `vroc_threshold`
  (default: 50%).
- **Minimal dependencies**: None — pure pandas on existing data.

### Scoring rationale
- **Ease (9)**: Near-trivial calculation on data already in memory. Essentially
  a one-liner plus config wiring.
- **Usefulness (8)**: Excellent fakeout filter. Slightly below 9 because volume
  on Binance spot can be noisy in off-hours, and the bot already partially accounts
  for conviction through multi-TF alignment counts.

---

## 3. ATR-Based Dynamic Stops

**Ease: 8/10 · Usefulness: 8/10 · Priority: 8.0**

### What it does
The Average True Range measures volatility as the average of
`max(high - low, |high - prev_close|, |low - prev_close|)` over N candles.
Stop-losses are set at 1.5–2× ATR from entry, widening in volatile markets
and tightening in calm ones.

### Why it matters for this bot
- The current exit strategy uses fixed percentage stops (20% trailing, 50% hard).
  These are arbitrary and get "hunted" during high-volatility BTC spikes.
- ATR-based stops are volatility-adaptive: wider when BTC is noisy (avoiding
  premature exits), tighter when calm (protecting gains).
- The existing BTC pressure scaling in `exits.py` already adjusts stops
  directionally — ATR would add a volatility dimension on top of that.

### Implementation notes
- **Calculation**: Standard ATR on 15m candles (already fetched).
  `true_range = max(high - low, abs(high - prev_close), abs(low - prev_close))`,
  then EMA or SMA of true_range over N periods.
- **Where it fits**: Replaces or supplements the fixed `trailing_stop_pct` and
  `hard_stop_pct` in `backend/trading/exits.py`. The `evaluate_exit()` function
  currently computes `base_trailing` from config — this would dynamically compute
  it from ATR instead.
- **Config additions**: `atr_period` (default: 14), `atr_stop_multiplier`
  (default: 1.5), `atr_enabled` toggle.
- **Challenge**: Need to translate BTC ATR (in USD) to Polymarket token percentage
  terms. The mapping isn't 1:1 since token prices are 0–1 binary probabilities.
  Would likely use ATR as a volatility regime classifier (high/medium/low) rather
  than a direct dollar stop.

### Scoring rationale
- **Ease (8)**: ATR calculation itself is simple. The complexity is in mapping
  BTC volatility to Polymarket token stop percentages and integrating with the
  existing pressure-scaling system without conflicting.
- **Usefulness (8)**: Addresses a real weakness in the current fixed-stop system.
  Would reduce both premature stop-outs in volatile periods and excessive loss in
  calm periods where tighter stops are appropriate.

---

## 4. Order Book Imbalance (OBI)

**Ease: 6/10 · Usefulness: 9/10 · Priority: 7.5**

### What it does
A ratio of resting bid size vs. ask size across the top 5–10 price levels:
`OBI = (bid_depth - ask_depth) / (bid_depth + ask_depth)`. Ranges from -1 (all
asks, no bids) to +1 (all bids, no asks).

### Why it matters for this bot
- This is a **leading indicator** — it shows the "road surface" before price
  travels it. Heavy bids + thin asks = path of least resistance is UP.
- Unlike lagging indicators (EMAs, RSI), OBI predicts the *next* candle rather
  than describing the current one. For 15-minute binary options, this is the
  difference between entering before or after the move.
- Can be computed for both BTC (Binance order book) and Polymarket tokens
  (CLOB order book), giving two independent views.

### Implementation notes
- **Data sources**:
  - Binance: `GET /api/v3/depth?symbol=BTCUSDT&limit=10` — new API call needed.
  - Polymarket: The CLOB client likely supports order book fetches. Models
    `OrderBookSnapshot` and `OrderBookLevel` already exist in `models.py`.
- **Where it fits**: New signal component, likely a Layer 3 or an enhancement to
  Layer 1/2. Could feed into `SignalEngine._combine_signals()` with its own weight.
- **Config additions**: `obi_depth_levels` (default: 10), `obi_weight` in signal
  combination, `obi_threshold` for trade gating.
- **Challenges**:
  - Requires new API endpoints and potentially WebSocket subscriptions for
    real-time order book updates.
  - Order books are noisy — spoofing and cancellations mean raw OBI can be
    misleading. May need smoothing (rolling average).
  - Rate limiting on Binance depth endpoint.

### Scoring rationale
- **Ease (6)**: Requires new data fetching infrastructure (Binance depth API,
  potentially Polymarket CLOB book). The `OrderBookSnapshot` model exists but
  isn't currently populated in the signal pipeline. Non-trivial plumbing.
- **Usefulness (9)**: Highest predictive value of any metric here. A leading
  indicator that directly forecasts price direction — exactly what a 15-minute
  binary option bot needs. The reason it's not a 10 is the noise/spoofing concern.

---

## 5. Volume Profile (HVN & LVN)

**Ease: 5/10 · Usefulness: 7/10 · Priority: 6.0**

### What it does
A horizontal histogram that aggregates volume at each price level rather than
over time. High Volume Nodes (HVN) are price levels where lots of trading occurred
(support/resistance). Low Volume Nodes (LVN) are "air pockets" where price moved
rapidly through.

### Why it matters for this bot
- HVNs act as institutional magnets — if BTC is near an HVN, price is likely to
  stall or reverse. Useful for gauging whether a 15-min candle will be range-bound.
- LVNs represent high-velocity zones — if BTC enters an LVN, it will likely move
  fast through it, increasing the probability of a directional binary outcome.
- Helps classify the "terrain" BTC must travel in the next 15 minutes.

### Implementation notes
- **Data**: Requires granular candle data (1m or finer) to build the profile.
  The Binance client already fetches 250 × 1m candles. Volume at price can be
  approximated by distributing each candle's volume across its high-low range.
- **Algorithm**:
  1. Define price bins (e.g., $50 increments for BTC).
  2. For each candle, distribute volume proportionally across price bins
     within the candle's range.
  3. Identify HVN (bins above 1.5× mean volume) and LVN (bins below 0.5× mean).
  4. Determine current price position relative to nearest HVN/LVN.
- **Where it fits**: New analysis function in `backend/signals/btc_ta.py`.
  Output could be a "terrain score" (+1 = LVN above, likely breakout;
  -1 = HVN above, likely resistance).
- **Challenges**:
  - Bin size selection affects results significantly.
  - Approximating volume distribution within a candle is inherently imprecise.
  - Needs enough history to be meaningful (last 24h minimum).

### Scoring rationale
- **Ease (5)**: More complex than simple indicator math. Requires price binning,
  volume distribution, HVN/LVN detection, and relating the profile to current
  price. Not hard algorithmically, but more engineering than the simpler metrics.
- **Usefulness (7)**: Useful context but somewhat indirect for binary options.
  The bot doesn't care about exact price targets — just direction. Volume profile
  helps with "will it move?" but the bot already partially addresses this through
  multi-TF alignment. More useful for range vs. trend classification.

---

## 6. Regime-Aware Take Profit Scaling

**Ease: 4/10 · Usefulness: 9/10 · Priority: 6.5**

### What it does
A classification system that identifies the current market regime — Trending
(strong directional moves) vs. Ranging (choppy, mean-reverting) — and adjusts
take-profit thresholds accordingly. In trending markets, hold longer and aim for
larger exits. In ranging markets, take profits quickly before reversion.

### Why it matters for this bot
- The current exit strategy uses fixed trailing stop percentages regardless of
  market regime. This means:
  - In trends: the bot exits too early via trailing stop, missing the full move.
  - In ranges: the bot holds too long, watching profits evaporate as price
    reverts to mean.
- Regime awareness directly solves the #1 failure mode of fixed-parameter systems.
- For 15-minute binary options, regime affects the optimal entry timing too:
  trending regimes favor breakout entries, ranging regimes favor
  mean-reversion entries.

### Implementation notes
- **Rule-based approach** (recommended first pass):
  - ADX (Average Directional Index) > 25 = trending, < 20 = ranging.
  - EMA slope: if the 15m EMA-20 slope over last 5 candles exceeds threshold,
    classify as trending.
  - Bollinger Band width: narrow bands = ranging, expanding bands = trending.
- **ML-based approach** (future enhancement):
  - Train a classifier on labeled historical data (trending/ranging periods).
  - Features: ADX, BB width, EMA slopes, volume patterns.
  - Higher accuracy but requires training data, model management, and
    potentially new dependencies (scikit-learn).
- **Where it fits**: New module `backend/signals/regime.py`. Feeds into
  `backend/trading/exits.py` to dynamically adjust `trailing_stop_pct`,
  `tightened_trailing_pct`, and potentially `hard_stop_pct`.
- **Config additions**: `regime_detection_method` (rule/ml),
  `trending_trailing_stop_pct`, `ranging_trailing_stop_pct`, `adx_period`,
  `adx_trending_threshold`.
- **Challenges**:
  - ADX requires computing +DI/-DI first (non-trivial multi-step calculation).
  - Regime changes happen mid-window — the system needs to handle transitions.
  - Risk of overfitting if using ML approach.
  - The exit system already has BTC pressure scaling and time-decay tightening.
    Regime awareness needs to complement these without creating conflicting
    signals.

### Scoring rationale
- **Ease (4)**: Most complex metric to implement properly. ADX alone is a
  multi-step indicator. Integrating regime classification into the exit strategy
  without conflicting with existing pressure scaling requires careful design.
  ML approach adds dependency and training pipeline overhead.
- **Usefulness (9)**: Addresses the single biggest weakness of any fixed-parameter
  trading system. Regime-aware exits would likely produce the largest improvement
  in bot P&L of any metric on this list. The only reason it's not a 10 is that
  the bot's 15-minute window naturally limits how much regime-mismatch can hurt.

---

## 7. Multi-Timeframe Trend Filter (EMA 20/50)

**Ease: 9/10 · Usefulness: 5/10 · Priority: 7.0**

### What it does
Short-term Exponential Moving Averages (EMA 20 and EMA 50) applied to higher
timeframes (1h, 4h) to ensure the bot only trades in the direction of the
dominant trend. Long setups only when EMA 20 > EMA 50 and rising; short setups
only when EMA 20 < EMA 50 and falling.

### Why it matters for this bot
- Trading against the higher-timeframe trend is statistically high-risk. A
  15-minute "Up" signal while the 1h/4h trend is firmly bearish is more likely
  to be a temporary pullback than a reversal.
- Acts as a hard filter to prevent counter-trend trades.

### Implementation notes
- **Current state**: The bot **already implements this concept**. Layer 2 in
  `btc_ta.py` computes EMA signals across 6 timeframes including 1h (EMA 12/26)
  and 4h (EMA 20/50). The veto mechanism at line 218-256 kills the signal if
  15m or 1h disagrees with the direction.
- **What's different**: The suggestion specifically uses EMA 20/50 on the higher
  TFs with a slope condition (EMA 20 must be *rising*, not just above EMA 50).
  Currently the bot checks position and crossover but not slope.
- **Where it fits**: Minor enhancement to `compute_ema_signal()` in
  `btc_ta.py` — add slope calculation for the shorter EMA and include it in
  the signal components.
- **Config additions**: `ema_slope_lookback` (default: 5 candles),
  `ema_slope_threshold` (minimum slope to consider trending).

### Scoring rationale
- **Ease (9)**: The infrastructure is already built. This is a refinement —
  adding slope detection to the existing EMA computation. Minimal new code.
- **Usefulness (5)**: Partially redundant with existing Layer 2 logic. The
  bot already has multi-TF EMA analysis with a veto mechanism. Adding slope
  detection is a worthwhile refinement but won't dramatically change behavior.
  The existing system already prevents most counter-trend trades.

---

## Implementation Roadmap

Recommended order based on priority score and dependency:

### Phase 1 — Quick Wins (signal filters using existing data)
1. **VROC** (Priority 8.5) — One-liner volume filter, immediate fakeout reduction.
2. **VWAP** (Priority 8.5) — Session fair-value benchmark, strong confirmation signal.
3. **Multi-TF Trend Filter refinement** (Priority 7.0) — Slope detection on existing EMAs.

### Phase 2 — Exit Strategy Upgrades
4. **ATR-Based Dynamic Stops** (Priority 8.0) — Volatility-adaptive exits.
5. **Regime-Aware Take Profit** (Priority 6.5) — Highest-impact but most complex.

### Phase 3 — New Data Sources
6. **Order Book Imbalance** (Priority 7.5) — Requires new API plumbing but highest predictive value.
7. **Volume Profile** (Priority 6.0) — Useful context layer but indirect for binary options.

---

*Last updated: 2026-02-10*
