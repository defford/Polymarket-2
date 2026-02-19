# Bot Trading Fix — Testing Plan

## Bugs Fixed

### 1. Strategy loop ERROR status never recovers (engine.py)
**Problem**: Any transient error (API timeout, network blip) permanently set bot status to ERROR. The loop kept running but the dashboard showed the bot as dead.
**Fix**: After the 10-second error sleep, reset status back to RUNNING/DRY_RUN if `_running` is still True.

### 2. Simple bot trading loop doesn't clean up on max errors (simple_bot_instance.py)
**Problem**: When 10 consecutive errors occurred, the loop broke and set `BotStatus.ERROR` but `_running` was never set to False. The bot appeared "running" but was dead. DB status was never updated, so it would auto-resume in the broken state on restart.
**Fix**: Set `_running = False` and update DB status to "error" before breaking.

### 3. Simple bot UNKNOWN order status caused duplicate orders (simple_bot_instance.py)
**Problem**: When `_check_order_status()` threw an exception and returned "UNKNOWN", the code fell through to the `else` block and placed a new order — creating duplicates while the original was still live.
**Fix**: Treat "UNKNOWN" the same as "OPEN" (wait and retry on next cycle). Applied to both `_handle_buy` and `_handle_sell`.

### 4. Simple bot `_close_position_from_fill` never found matching trades (simple_bot_instance.py)
**Problem**: After a sell order filled, the code searched for trades with `status == PENDING`, but the sell order never created a PENDING trade record in the DB. The buy trade was already FILLED. Result: position was never closed, bot got permanently stuck.
**Fix**: Search for `status == FILLED and pnl is None` (the buy trade that hasn't been closed yet). Calculate P&L directly from position data.

### 5. SwarmManager auto-resume silently swallowed start failures (swarm.py)
**Problem**: `asyncio.create_task(instance.start())` fire-and-forgot the start coroutine. If `start()` failed (auth error, etc.), nobody caught it. The DB still showed "running" but the bot was dead.
**Fix**: Added `_safe_start_bot()` wrapper that catches exceptions and updates DB status to "error" on failure.

## Programmatic Testing

### Test 1: Strategy loop error recovery
```python
# In a test file or REPL after starting the server:
# 1. Start a full bot in dry_run mode
# 2. Monitor logs for "Strategy loop error" messages
# 3. Verify the status cycles: ERROR -> (10s) -> DRY_RUN
# 4. Confirm the bot continues trading after recovery

# Check via API:
# GET /api/swarm/{bot_id}/status
# After a transient error, status should return to "dry_run" not stay "error"
```

### Test 2: Simple bot max error handling
```python
# 1. Start a simple bot
# 2. Force 10+ consecutive errors (e.g., by pointing to invalid market_condition_id)
# 3. Verify:
#    - Bot status transitions to "error"
#    - Bot is_running becomes False
#    - DB status updates to "error"
#    - Bot does NOT auto-resume on server restart

# Check via API:
# GET /api/swarm/{bot_id}/status -> {"status": "error", "is_running": false}
```

### Test 3: Simple bot order status handling
```python
# 1. Start a simple bot in live mode
# 2. Place a buy order
# 3. Check that _current_order_id is set
# 4. Simulate API errors on order status check
# 5. Verify no duplicate orders are placed (check Polymarket open orders)

# Monitor logs:
# Should see "UNKNOWN" treated as "OPEN" with no new order placement
```

### Test 4: Simple bot sell position closure
```python
# 1. Start a simple bot in dry_run mode with buy_price above current market price
# 2. Wait for buy fill simulation
# 3. Set sell_price achievable
# 4. Wait for sell fill simulation
# 5. Verify:
#    - Position is cleared (open_positions = [])
#    - Buy trade has pnl set (not None)
#    - Bot continues to place new buy orders

# Check via API:
# GET /api/swarm/{bot_id}/state -> open_positions should be []
# GET /api/swarm/{bot_id}/trades -> latest trade should have pnl != null
```

### Test 5: Auto-resume failure handling
```python
# 1. Create a bot configured for live mode without valid credentials
# 2. Set DB status to "running" manually
# 3. Restart the server
# 4. Verify:
#    - Error is logged with full traceback
#    - DB status updates to "error"
#    - Bot does not appear as running in the dashboard
```

## Manual Testing

1. **Start a simple bot in dry_run mode**
   - Confirm it cycles through buy -> fill -> sell -> fill -> buy repeatedly
   - Check the dashboard updates in real-time via WebSocket
   - Verify P&L accumulates correctly

2. **Start a full bot in dry_run mode**
   - Confirm it discovers markets, computes signals, and places trades
   - Trigger a simulated error by temporarily disconnecting network
   - Verify the bot recovers (status goes back to DRY_RUN after error)

3. **Create multiple bots and verify independence**
   - Start 2+ bots simultaneously
   - Verify each bot's trades have correct bot_id
   - Verify stopping one doesn't affect others

4. **Server restart resilience**
   - Start bots, then restart the server (Ctrl+C then restart)
   - Verify running bots auto-resume
   - Verify stopped bots stay stopped
   - Verify errored bots don't auto-resume
