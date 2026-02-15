# Bayesian Signal Weighting Engine — Implementation Summary

## Overview

This document summarizes the implementation of the Bayesian Signal Weighting Engine for the Polymarket BTC 15-minute trading bot. The system replaces fixed signal weights with a probabilistic approach that calculates `P(Win|Signals)` based on historical performance.

## Key Decisions (User-Selected)

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Min trades before activation | 50 | Ensures reliable estimates before Bayesian kicks in |
| Position sizing mode | Threshold gate | Block trades if posterior < 0.4, full size otherwise |
| Unseen evidence handling | Fallback to fixed weights | Uses existing layer1_weight/layer2_weight for novel combinations |

## Files Modified/Created

### New Files
| File | Purpose |
|------|---------|
| `backend/bayesian_manager.py` | Core Bayesian inference logic |
| `backend/tests/test_bayesian.py` | Unit tests (22 tests, all passing) |
| `backend/tests/__init__.py` | Test package marker |

### Modified Files
| File | Changes |
|------|---------|
| `backend/config.py` | Added `BayesianConfig` dataclass |
| `backend/models.py` | Extended `CompositeSignal` with evidence and Bayesian fields |
| `backend/database.py` | Added `bayesian_likelihood` table and queries |
| `backend/signals/engine.py` | Added evidence binning to signal computation |
| `backend/bot_instance.py` | Initialize `BayesianManager` per bot |
| `backend/trading/engine.py` | Integrated posterior calculation and gate |
| `backend/trading/risk.py` | Added Bayesian logging |
| `backend/main.py` | Added Bayesian API endpoints |
| `bot_config.json` | Added `bayesian` configuration section |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SLOW STRATEGY LOOP (~10s)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   1. SignalEngine.compute_signal(market)                           │
│      ↓                                                              │
│      Returns: CompositeSignal + (l1_evidence, l2_evidence)          │
│                                                                     │
│   2. BayesianManager.compute_posterior(l1_evidence, l2_evidence)    │
│      ↓                                                              │
│      Returns: { posterior, prior, confidence_gate, fallback }       │
│                                                                     │
│   3. IF confidence_gate == False → BLOCK TRADE                     │
│      ELSE → Proceed with existing logic                             │
│                                                                     │
│   4. After trade resolution:                                        │
│      BayesianManager.record_outcome(l1_evidence, l2_evidence, won)  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Evidence Categories

### Layer 1 (Polymarket Sentiment)
| Category | Direction Range |
|----------|-----------------|
| `L1_BULLISH_STRONG` | +0.5 to +1.0 |
| `L1_BULLISH_WEAK` | +0.2 to +0.5 |
| `L1_NEUTRAL` | -0.2 to +0.2 |
| `L1_BEARISH_WEAK` | -0.5 to -0.2 |
| `L1_BEARISH_STRONG` | -1.0 to -0.5 |

### Layer 2 (BTC Technicals)
| Category | Direction Range |
|----------|-----------------|
| `L2_BULLISH_STRONG` | +0.5 to +1.0 |
| `L2_BULLISH_WEAK` | +0.2 to +0.5 |
| `L2_NEUTRAL` | -0.2 to +0.2 |
| `L2_BEARISH_WEAK` | -0.5 to -0.2 |
| `L2_BEARISH_STRONG` | -1.0 to -0.5 |

## Database Schema

### New Table: `bayesian_likelihood`

```sql
CREATE TABLE bayesian_likelihood (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id INTEGER NOT NULL,
    l1_evidence TEXT NOT NULL,
    l2_evidence TEXT NOT NULL,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,
    last_updated TEXT NOT NULL,
    UNIQUE(bot_id, l1_evidence, l2_evidence)
);
```

### New Columns in `trades`
- `l1_evidence TEXT` — Layer 1 evidence category at trade entry
- `l2_evidence TEXT` — Layer 2 evidence category at trade entry

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/swarm/{bot_id}/bayesian/likelihood` | View likelihood table |
| GET | `/api/swarm/{bot_id}/bayesian/stats` | Bayesian statistics |
| POST | `/api/swarm/{bot_id}/bayesian/reset` | Clear likelihood history |

## Configuration

### BayesianConfig Parameters

```json
{
  "bayesian": {
    "enabled": true,
    "rolling_window": 100,
    "min_sample_size": 50,
    "default_confidence": 0.5,
    "confidence_threshold": 0.4,
    "smoothing_alpha": 0.1
  }
}
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `enabled` | true | Master switch for Bayesian inference |
| `rolling_window` | 100 | Trades used for prior calculation |
| `min_sample_size` | 50 | Minimum trades before Bayesian activates |
| `default_confidence` | 0.5 | Fallback confidence when insufficient data |
| `confidence_threshold` | 0.4 | Gate threshold (trades blocked below this) |
| `smoothing_alpha` | 0.1 | Laplace smoothing for likelihoods |

## Testing

### Manual Testing Steps

1. **Start the bot in dry-run mode:**
   ```bash
   cd backend
   python3 main.py
   ```

2. **Check Bayesian status:**
   ```bash
   curl http://127.0.0.1:8000/api/swarm/1/bayesian/stats
   ```

3. **Start the bot:**
   ```bash
   curl -X POST http://127.0.0.1:8000/api/swarm/1/start
   ```

4. **Monitor logs for Bayesian messages:**
   - `📊 Bayesian POSTERIOR: 0.65 (prior=0.55)` — Trade allowed
   - `🚫 Bayesian gate BLOCKED: posterior=0.32` — Trade blocked

5. **After some trades, check likelihood table:**
   ```bash
   curl http://127.0.0.1:8000/api/swarm/1/bayesian/likelihood
   ```

### Unit Tests

Run tests:
```bash
cd backend
python3 -m pytest tests/test_bayesian.py -v
```

Expected: 22 tests passing

## Monitoring Points

Key log messages to monitor:

| Log Pattern | Meaning |
|-------------|---------|
| `Bayesian likelihood updated` | Outcome recorded to DB |
| `Bayesian POSTERIOR: X.XX` | Trade allowed (above threshold) |
| `Bayesian gate BLOCKED` | Trade blocked (below threshold) |
| `insufficient_history` | Fallback mode (< 50 trades) |
| `unseen_evidence_combination` | Fallback mode (novel signal pair) |

## Swarm Compatibility

Each bot in the swarm maintains its own Bayesian likelihood table. The `bot_id` is used to partition data, ensuring:
- Bot 1's history doesn't affect Bot 2's posteriors
- Each bot learns from its own trading patterns
- Configuration can be tuned per-bot via the API

## Performance Considerations

- Bayesian computation happens in the **Slow Strategy Loop** (~10s), not the Fast Risk Loop
- Prior is cached for 60 seconds to avoid repeated DB queries
- Database operations use WAL mode for concurrent access safety
- Evidence binning is O(1) — just threshold comparisons