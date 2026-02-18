# Simple Bots Implementation Plan

## Overview

Simple Bots are a stripped-down version of trading bots that execute basic limit order rules without any complex configuration. They place standing limit orders at specified prices and cycle through buy→sell until stopped.

## User Flow Example

1. User says: "Make a bot that buys UP at 50 cents and sells at 75 cents"
2. System creates a Simple Bot with:
   - Side: UP
   - Buy price: 0.50
   - Sell price: 0.75
   - Market: Current active 15-min BTC market
   - Size: $5 (default, configurable)
3. Bot appears in swarm dashboard
4. Bot places standing limit buy at 50c, waits for fill
5. Once filled, places standing limit sell at 75c
6. Once sold, repeats from step 4

## Design Decisions

| Question | Decision |
|----------|----------|
| Order behavior | Standing limit orders (places order and waits for fill) |
| Market scope | Single market (current 15-min BTC market) |
| Position sizing | Fixed USD amount (user specifies, e.g., $5) |
| Repeating | Repeat indefinitely until stopped |

---

## Implementation

### 1. Database Changes

Add columns to the existing `bots` table:

```sql
ALTER TABLE bots ADD COLUMN is_simple INTEGER DEFAULT 0;
ALTER TABLE bots ADD COLUMN simple_rules_json TEXT DEFAULT NULL;
```

### 2. New Data Models

**File: `backend/models.py`**

```python
class SimpleBotRule(BaseModel):
    """Rule configuration for a Simple Bot."""
    market_condition_id: Optional[str] = None  # None = use current active market
    buy_side: Side  # UP or DOWN
    buy_price: float  # 0.01 to 0.99
    sell_price: float  # 0.01 to 0.99
    size_usd: float  # Amount to spend per cycle


class CreateSimpleBotRequest(BaseModel):
    """Request body for creating a simple bot."""
    name: str
    description: str = ""
    buy_side: str  # "up" or "down"
    buy_price: float  # e.g., 0.50 for 50 cents
    sell_price: float  # e.g., 0.75 for 75 cents
    size_usd: float = 5.0  # default $5
    market_condition_id: Optional[str] = None  # None = current market
```

### 3. SimpleBotInstance Class

**File: `backend/simple_bot_instance.py`** (New file)

A lightweight bot instance that:
- Has no signal engine, risk manager, or complex config
- Uses its own PolymarketClient (like regular bots)
- Has a simple OrderManager for order placement
- Implements a straightforward trading loop

### 4. Simple Trading Logic

**File: `backend/simple_bot_engine.py`** (New file)

Core trading loop:
1. Get current market (if not fixed to specific market)
2. Place standing limit buy at rule.buy_price
3. Poll for fill (with timeout handling)
4. Once filled, place standing limit sell at rule.sell_price
5. Poll for fill
6. Record P&L
7. Repeat from step 1

### 5. SwarmManager Updates

**File: `backend/swarm.py`**

- Add `_simple_bots: dict[int, SimpleBotInstance]` 
- Modify `_create_instance()` to handle simple bots
- Add `create_simple_bot()` method
- Reuse existing `start_bot()`, `stop_bot()`, `get_bot()` methods

### 6. API Endpoints

**File: `backend/main.py`**

```python
@app.post("/api/simple-bot")
async def create_simple_bot(request: CreateSimpleBotRequest):
    """Create a new simple bot with basic trading rules."""
```

Reuse existing endpoints for start/stop/state/trades.

### 7. Frontend Changes

**New file: `frontend/src/components/AddSimpleBotModal.jsx`**

Form with:
- Name input
- Side selector (UP/DOWN)
- Buy price input (cents)
- Sell price input (cents)
- Size input (USD)

**Modified: `frontend/src/components/SwarmView.jsx`**

Add "Add Simple Bot" button alongside existing "Add Bot" button.

**Modified: `frontend/src/components/BotCard.jsx`**

Add visual indicator for simple bots (badge or different styling).

---

## Files to Create/Modify

### New Files
1. `backend/simple_bot_instance.py` - SimpleBotInstance class
2. `backend/simple_bot_engine.py` - Trading loop logic
3. `frontend/src/components/AddSimpleBotModal.jsx` - Frontend modal

### Modified Files
1. `backend/models.py` - Add SimpleBotRule, CreateSimpleBotRequest
2. `backend/database.py` - Add migration for is_simple, simple_rules_json columns
3. `backend/swarm.py` - Handle simple bots alongside regular bots
4. `backend/main.py` - Add POST /api/simple-bot endpoint
5. `frontend/src/components/SwarmView.jsx` - Add "Add Simple Bot" button
6. `frontend/src/components/BotCard.jsx` - Show simple bot indicator

---

## Testing Plan

### Manual Testing

1. **Create Simple Bot** - Use API/frontend, verify appears in swarm
2. **Start Bot** - Verify limit order placed at buy price
3. **Wait for Fill** - Verify bot detects fill, places sell order
4. **Complete Cycle** - Verify P&L recorded, next cycle starts
5. **Stop Bot** - Verify orders cancelled, position tracked

### Programmatic Testing

```python
def test_create_simple_bot():
    rule = SimpleBotRule(buy_side=Side.UP, buy_price=0.50, sell_price=0.75, size_usd=5.0)
    bot_id = swarm_manager.create_simple_bot("Test", rule)
    assert swarm_manager.get_bot(bot_id).is_simple == True
```

---

## Edge Cases

1. **Market closes before fill** - Cancel order, wait for new market
2. **Position at market close** - Let resolve naturally, record P&L
3. **API errors** - Retry with backoff, mark ERROR if persistent
4. **Partial fills** - Use postOnly limit orders, track actual size
