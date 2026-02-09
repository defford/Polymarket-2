# Phase 1: Advanced Trade Metrics Implementation Plan

## Overview
Add 4 new metric categories to the trading bot's instrumentation and analysis pipeline:
1. **Slippage Tracking** — Signal price vs fill price
2. **MAE/MFE Tracking** — Max Adverse/Favorable Excursion during position lifetime
3. **Fill Rate Tracking** — FOK order success rates
4. **Order Book Imbalance** — Bid/ask volume ratios at entry/exit

## Files to Modify

### Backend

| File | Changes |
|------|---------|
| `backend/models.py` | Add `trough_price` to `Position` model |
| `backend/polymarket/orders.py` | Capture slippage data at entry/exit, persist MAE/MFE and OBI at exit, track fill metadata |
| `backend/trading/engine.py` | Track `trough_price` in fast risk loop, compute OBI in `_capture_market_state()` |
| `backend/analysis/engine.py` | Add 4 new analysis methods |
| `frontend/src/components/AnalysisPanel.jsx` | Add 4 new display sections |

### No schema changes needed
All new data is stored in the existing `trade_log_data` JSON column — fully backward compatible.

---

## 1. Slippage Tracking

### What we capture
- **Entry slippage**: `requested_price` (the limit/market price we asked for) vs `fill_price` (actual avgPrice from API)
- **Exit slippage**: `requested_sell_price` (get_price at exit) vs `actual_sell_price` (avgPrice from fill)
- Stored as basis points: `slippage_bps = (fill_price - requested_price) / requested_price * 10000`

### Implementation

**`orders.py` — `place_order()`**
- Before order placement, record `requested_price = price`
- After fill verification (lines 183-189), record `actual_fill_price`
- Add to `log_entry`:
  ```python
  log_entry["entry_slippage"] = {
      "requested_price": requested_price,
      "fill_price": actual_fill_price,
      "slippage_bps": (actual_fill_price - requested_price) / requested_price * 10000,
      "order_type": order_type,
  }
  ```
- For dry run: slippage = 0 (fill at requested price)

**`orders.py` — `sell_position()`**
- Record `requested_sell_price = sell_price` before live sell
- After fill (lines 434-455), compute exit slippage
- Add to `log_entry`:
  ```python
  log_entry["exit_slippage"] = {
      "requested_price": requested_sell_price,
      "fill_price": actual_sell_price,
      "slippage_bps": ...,
  }
  ```

**`analysis/engine.py` — `_slippage_analysis()`**
- Avg entry slippage (bps)
- Avg exit slippage (bps)
- Total slippage cost ($)
- Slippage by order type (market vs limit vs postOnly)
- Slippage impact on PnL (how much PnL was lost to slippage)

---

## 2. MAE/MFE Tracking

### What we capture
- **MAE (Max Adverse Excursion)**: Largest drawdown from entry before exit
- **MFE (Max Favorable Excursion)**: Largest profit from entry before exit
- Already track `peak_price` — need to add `trough_price`

### Implementation

**`models.py` — `Position`**
- Add `trough_price: float = 0.0` field (lowest price since entry)

**`orders.py` — `place_order()`**
- Set `trough_price = price` when creating Position (same as entry_price)

**`engine.py` — `_fast_risk_loop()`** (line 320-324)
- After updating `peak_price`, also update `trough_price`:
  ```python
  if ws_price < position.trough_price or position.trough_price == 0:
      position.trough_price = ws_price
  ```

**`orders.py` — `sell_position()` and `resolve_position()`**
- Compute and store in log_entry:
  ```python
  log_entry["mae_mfe"] = {
      "entry_price": position.entry_price,
      "peak_price": position.peak_price,
      "trough_price": position.trough_price,
      "exit_price": sell_price,
      "mae_pct": (position.entry_price - position.trough_price) / position.entry_price,
      "mfe_pct": (position.peak_price - position.entry_price) / position.entry_price,
      "capture_ratio": actual_return / mfe if mfe > 0 else 0,
  }
  ```
- `capture_ratio` = how much of the max profit did we actually capture

**`analysis/engine.py` — `_mae_mfe_analysis()`**
- Avg MAE for winners vs losers
- Avg MFE for winners vs losers
- Avg capture ratio (MFE utilization)
- MAE distribution: how many trades dip X% before recovering
- "Missed profit" = avg (MFE - actual return) for winners

---

## 3. Fill Rate Tracking

### What we capture
- Whether order was FOK (market) or limit/postOnly
- Fill outcome: filled, cancelled, rejected, partial
- Time to fill (seconds)
- Number of retries before fill

### Implementation

**`orders.py` — `place_order()`**
- Track `fill_start_time = time.time()` before verification loop
- Track `fill_retries` counter
- Add to `log_entry`:
  ```python
  log_entry["fill_info"] = {
      "order_type": order_type,
      "was_fok": order_type == "market",
      "fill_status": "filled" | "cancelled" | "rejected",
      "time_to_fill_seconds": time.time() - fill_start_time,
      "retries": fill_retries,
      "requested_size": size_tokens,
  }
  ```
- For dry run: `fill_status = "filled"`, `time_to_fill = 0`, `retries = 0`

**`analysis/engine.py` — `_fill_rate_analysis()`**
- Overall fill rate (filled / total attempts)
- Fill rate by order type (FOK vs limit vs postOnly)
- Avg time to fill
- Trades missed due to fill failure (cancelled/rejected count)
- PnL of FOK trades vs limit trades

---

## 4. Order Book Imbalance

### What we capture
- Bid/ask volume imbalance at entry and exit
- Spread at entry and exit
- Depth at top N levels

### Implementation

**`engine.py` — new helper `_compute_orderbook_imbalance()`**
```python
def _compute_orderbook_imbalance(self, orderbook: dict) -> dict:
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    bid_vol = sum(float(b.get("size", 0)) for b in bids[:5])
    ask_vol = sum(float(a.get("size", 0)) for a in asks[:5])
    total = bid_vol + ask_vol

    best_bid = float(bids[0]["price"]) if bids else 0
    best_ask = float(asks[0]["price"]) if asks else 0

    return {
        "bid_volume_top5": round(bid_vol, 2),
        "ask_volume_top5": round(ask_vol, 2),
        "imbalance": round((bid_vol - ask_vol) / total, 4) if total > 0 else 0,
        "spread": round(best_ask - best_bid, 4) if best_bid and best_ask else 0,
        "best_bid": best_bid,
        "best_ask": best_ask,
    }
```

**`orders.py` — `place_order()` and `sell_position()`**
- Extract OBI from buy_state_snapshot/sell_state_snapshot orderbooks
- Add to `log_entry`:
  ```python
  log_entry["orderbook_imbalance_entry"] = compute_from_buy_state(...)
  log_entry["orderbook_imbalance_exit"] = compute_from_sell_state(...)
  ```

**`analysis/engine.py` — `_orderbook_analysis()`**
- Avg imbalance at entry for winners vs losers
- Spread at entry vs PnL correlation
- Best imbalance range for profitable trades

---

## Frontend Display

### AnalysisPanel.jsx — 4 new CollapsibleSection components

1. **SlippageAnalysis** — Table: order type | avg entry slippage | avg exit slippage | total cost
2. **MaeMfeAnalysis** — Table: metric | winners | losers + capture ratio stat
3. **FillRateAnalysis** — Table: order type | fill rate | avg time | count
4. **OrderbookAnalysis** — Table: metric | winners | losers (imbalance, spread)

---

## Testing Plan

### Programmatic Tests
1. Run the bot in dry_run mode — verify new fields appear in `trade_log_data` JSON
2. Query `GET /api/analysis/latest` — verify new metric categories are present
3. Check backward compatibility — old trades without new fields should not break analysis

### Manual Tests
1. Start a bot, let it make a few trades
2. Open Analysis Panel → Run Analysis → verify 4 new sections appear
3. Check that dry-run trades show 0 slippage (expected)
4. Check that MAE/MFE values are reasonable (MAE >= 0, MFE >= 0)
5. Check that OBI values make sense (imbalance between -1 and 1)
6. Verify old analysis sections still work correctly
