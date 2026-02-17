# Test Plan: Trade Price History Chart

## Feature Overview
Adds a 15-minute price history chart to the trade detail modal, showing both up and down token prices with entry/exit markers.

## Files Changed

### Backend
- `backend/main.py` — Added `GET /api/trades/{trade_id}/price-history` endpoint

### Frontend
- `frontend/src/components/PriceHistoryChart.jsx` — New chart component
- `frontend/src/components/TradeDetailModal.jsx` — Integrated chart into modal

---

## Manual Testing Steps

### 1. Start the Application
```bash
# Terminal 1: Start backend
cd backend
python main.py

# Terminal 2: Start frontend
cd frontend
npm run dev
```

### 2. Navigate to Trade History
1. Open the dashboard in browser (http://localhost:5173)
2. Click on a bot to view details
3. Navigate to Trade History section
4. Click on a trade row to open the detail modal

### 3. Verify Price History Chart
- [ ] Chart appears as a collapsible section titled "Price History (15-Min Window)"
- [ ] Section is expanded by default
- [ ] Chart shows X-axis from Minute 0 to Minute 15
- [ ] Chart shows Y-axis with prices in cents (¢0 to ¢100)
- [ ] Green line shows Up token prices
- [ ] Red line shows Down token prices
- [ ] Legend appears below chart showing both tokens

### 4. Verify Entry/Exit Markers
- [ ] Entry dot appears on the traded token's line at the correct minute
- [ ] Entry dot is a filled circle with white border
- [ ] Exit dot appears if trade has exited (dashed border style)
- [ ] Entry/Exit labels appear below chart with minute numbers

### 5. Test Edge Cases
- [ ] Trade without log data shows "Price history unavailable" message
- [ ] Loading state shows spinner while fetching
- [ ] Price history API failure shows appropriate error message

---

## Programmatic Testing

### Test Backend Endpoint
```bash
# Get price history for trade ID 1
curl http://localhost:8000/api/trades/1/price-history | jq

# Expected response structure:
# {
#   "available": true,
#   "up_prices": [{"minute": 0, "price": 0.50}, ...],
#   "down_prices": [{"minute": 0, "price": 0.50}, ...],
#   "entry_minute": 5,
#   "entry_price": 0.52,
#   "exit_minute": 12,
#   "exit_price": 0.48,
#   "trade_side": "up",
#   "window_start": 1234567890,
#   "window_end": 1234568790
# }

# Test with non-existent trade
curl http://localhost:8000/api/trades/99999/price-history
# Expected: {"detail": "Trade not found"}

# Test with trade without log data
curl http://localhost:8000/api/trades/<trade_id_without_logs>/price-history
# Expected: {"available": false, "reason": "No log data available for this trade", ...}
```

### Test Frontend Component
1. Open browser DevTools
2. Navigate to trade detail modal
3. Check Network tab for `/api/trades/{id}/price-history` request
4. Verify response data matches expected structure
5. Check Console for any React errors

---

## Test Cases

| Test Case | Input | Expected Output |
|-----------|-------|-----------------|
| Normal trade with exit | Trade with log data & exit | Chart shows both entry and exit dots |
| Trade still open | Trade without exit data | Chart shows only entry dot |
| Trade without log data | Trade missing log_data | "Price history unavailable" message |
| Invalid trade ID | Non-existent trade ID | 404 error from API |
| Price API failure | Polymarket API unreachable | "Price history unavailable" with reason |

---

## Known Limitations

1. Price history relies on Polymarket's `/prices-history` API endpoint
2. Historical prices may not be available for very old markets
3. Price fidelity is approximately 1 minute (controlled by `fidelity=60` parameter)
4. Entry/exit times are approximate based on trade timestamp and duration

---

## Build Verification

```bash
cd frontend && npm run build
```

Expected: Build succeeds without errors.
