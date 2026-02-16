# High-Conviction Trading Strategy - Testing Plan

## Overview

This document outlines the testing strategy for the new high-conviction trading parameters.

## Implemented Features

### 1. High-Conviction Filter
- **Buy Threshold**: Changed from `0.10` to `0.30`
- **Order Type**: `postOnly` (already configured)
- Ensures only high-quality signals trigger trades

### 2. Initial Survival Buffer
- **Duration**: First 180 seconds of every trade
- **Hard Stop**: 15 BPS (0.15%) from entry
- **Trailing Stop**: DISABLED during survival buffer
- **Purpose**: Allow trade to survive early noise, prevent immediate stop-outs

### 3. Time-Delayed Trailing Stop
- **Activation**: After 180 seconds
- **Condition**: Only if position is profitable (`current_price > entry_price`)
- **If Underwater**: Keep hard stop only, no trailing

### 4. Dynamic Conviction Scaling
| Conviction Level | Threshold | Action |
|------------------|-----------|--------|
| **High** | `> 0.45` | TP = 35%, hold longer |
| **Normal** | `0.25 - 0.45` | Standard exits |
| **Low** | `< 0.25` | Tighten trail to 0.1%, secure win quickly |

---

## Programmatic Testing

### Unit Tests to Add

```python
# backend/tests/test_survival_buffer.py

def test_survival_buffer_blocks_trailing():
    """Trailing stop should NOT trigger during survival buffer."""
    # Create position held for 60 seconds (< 180)
    # Simulate 5% drop from peak
    # Assert NO trailing stop exit

def test_survival_hard_stop_triggers():
    """15 BPS hard stop should trigger during buffer."""
    # Create position held for 60 seconds
    # Simulate 0.2% drop from entry (> 15 BPS)
    # Assert survival_hard_stop exit

def test_trailing_activates_after_buffer():
    """Trailing should activate after buffer IF profitable."""
    # Create position held for 200 seconds (> 180)
    # Position is profitable
    # Simulate drop >= trailing_stop_pct
    # Assert trailing_stop exit

def test_no_trailing_when_underwater():
    """Trailing should NOT activate if underwater."""
    # Create position held for 200 seconds
    # Position is NOT profitable
    # Simulate drop from peak
    # Assert NO trailing exit (only hard stop)

def test_high_conviction_extended_tp():
    """High conviction should use extended TP."""
    # Position with conviction 0.50 (> 0.45)
    # Price rises 30% (< 35% TP)
    # Assert NO exit
    # Price rises 36% (> 35% TP)
    # Assert hard_take_profit exit

def test_low_conviction_tight_trail():
    """Low conviction should use tight trail."""
    # Position with conviction 0.20 (< 0.25)
    # Simulate 0.15% drop from peak (> 0.1% trail)
    # Assert trailing_stop exit with tight trail
```

### Integration Tests

```bash
# Run existing test suite
cd backend && python -m pytest tests/ -v

# Type checking
mypy backend/
```

---

## Manual Testing Checklist

### 1. Survival Buffer Verification

Run bot in `dry_run` mode and monitor logs for:

- [ ] **Entry logged with conviction**: Check `entry_conviction` is captured
- [ ] **< 180s behavior**: 
  - [ ] No trailing stop messages in first 180s
  - [ ] `survival_hard_stop` exit if price drops > 15 BPS
  - [ ] Log shows `time_zone=SURVIVAL`
- [ ] **> 180s behavior**:
  - [ ] Trailing stop activates (if profitable)
  - [ ] Log shows transition from `SURVIVAL` to `normal`

### 2. Conviction Scaling Verification

Monitor trades and verify:

- [ ] **High conviction (> 0.45)**:
  - [ ] Log shows `conviction_tier=high`
  - [ ] TP target is 35% (not 25%)
  - [ ] Position holds longer

- [ ] **Low conviction (< 0.25)**:
  - [ ] Log shows `conviction_tier=low`
  - [ ] Trailing stop tightens to 0.1%
  - [ ] Early exit on small gains

### 3. Profit-Based Trailing

- [ ] **Profitable position**: Trailing activates after buffer
- [ ] **Underwater position**: Only hard stop active, no trailing

### 4. Frontend Configuration

- [ ] Open Config Panel
- [ ] Verify new fields appear:
  - [ ] Survival Buffer toggle
  - [ ] Buffer Duration (sec)
  - [ ] Hard Stop (BPS)
  - [ ] High Conviction Threshold
  - [ ] High Conviction TP %
  - [ ] Low Conviction Threshold
  - [ ] Low Conviction Trail %
- [ ] Change values and save
- [ ] Refresh page, verify persistence

---

## Log Patterns to Watch

### Survival Buffer Active
```
📉 EXIT CHECK: UP | entry=0.450 peak=0.455 now=0.449 (drop=1.3%) | conviction=0.35 (normal) | BTC pressure=+0.15 -> multiplier=1.00 | stop=100.0% TP=25.0% (SURVIVAL) | held=45s left=720s
```

### Survival Hard Stop Triggered
```
🛑 EXIT TRIGGERED -- survival_hard_stop: price 0.449 dropped 0.22% from entry 0.450 (survival buffer: 0.15% for 45s)
```

### Trailing After Buffer (Profitable)
```
📉 EXIT CHECK: UP | entry=0.450 peak=0.480 now=0.465 (drop=3.1%) | conviction=0.50 (high) | ... | stop=25.0% TP=35.0% (normal) | held=200s left=600s
```

### Low Conviction Tight Exit
```
🎯 EXIT TRIGGERED -- low_conviction_take_profit: conviction=0.20 < 0.25 | securing win at 0.475
```

---

## Configuration Reference

### bot_config.json (Exit Section)

```json
{
  "exit": {
    "enabled": true,
    "trailing_stop_pct": 0.25,
    "hard_stop_pct": 0.5,
    "survival_buffer_enabled": true,
    "survival_buffer_seconds": 180,
    "survival_hard_stop_bps": 15.0,
    "high_conviction_threshold": 0.45,
    "high_conviction_tp_pct": 0.35,
    "low_conviction_threshold": 0.25,
    "low_conviction_trail_pct": 0.001
  }
}
```

### Parameter Defaults (config.py)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `survival_buffer_enabled` | `True` | Master switch |
| `survival_buffer_seconds` | `180` | 3 minutes |
| `survival_hard_stop_bps` | `15.0` | 0.15% |
| `high_conviction_threshold` | `0.45` | Conviction above this = high |
| `high_conviction_tp_pct` | `0.35` | 35% TP for high conviction |
| `low_conviction_threshold` | `0.25` | Conviction below this = low |
| `low_conviction_trail_pct` | `0.001` | 0.1% trail for low conviction |

---

## Risk Considerations

1. **Survival Buffer Risk**: 15 BPS stop is very tight. In volatile conditions, may cause frequent exits. Monitor `survival_hard_stop` exit frequency.

2. **High Conviction Extended TP**: 35% TP may not trigger often. Monitor if high-conviction trades are closing via trailing stop instead.

3. **Low Conviction Exits**: Tight 0.1% trail may exit too early on winning trades. Review `low_conviction_take_profit` vs `trailing_stop` frequency.

---

## Rollback Plan

If issues arise, disable features in `bot_config.json`:

```json
{
  "exit": {
    "survival_buffer_enabled": false,
    "high_conviction_threshold": 1.0,
    "low_conviction_threshold": 0.0
  },
  "signal": {
    "buy_threshold": 0.10
  }
}
```

This reverts to previous behavior while keeping code compatible.
