# Polymarket BTC 15-Min Trading Bot — Architecture Plan

## Overview

A fully automated directional trading bot for Polymarket's BTC 15-minute Up/Down prediction markets, with a React dashboard for monitoring, parameter tuning, and backtesting.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   React Frontend (Vite)                  │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │Dashboard │  │ Param Tuning │  │   Backtesting     │  │
│  │ - P&L    │  │ - Indicators │  │ - Historical runs │  │
│  │ - Trades │  │ - Risk mgmt  │  │ - Equity curves   │  │
│  │ - Market │  │ - Signals    │  │ - Stats           │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
│                         │                                │
│                    WebSocket + REST                       │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────┴───────────────────────────────────┐
│                 FastAPI Backend (Python)                  │
│                                                          │
│  ┌─────────────────┐  ┌──────────────────────────────┐  │
│  │  Signal Engine   │  │      Trading Engine          │  │
│  │                  │  │                              │  │
│  │  Layer 1:        │  │  - Order management          │  │
│  │  Polymarket TA   │  │  - Position tracking         │  │
│  │  (RSI, MACD on   │  │  - Risk controls             │  │
│  │   token prices)  │  │  - Market rotation           │  │
│  │                  │  │    (auto-switch every 15min)  │  │
│  │  Layer 2:        │  │                              │  │
│  │  BTC Price TA    │  │                              │  │
│  │  (Multi-TF EMAs) │  │                              │  │
│  └────────┬─────────┘  └──────────┬───────────────────┘  │
│           │                       │                      │
│  ┌────────┴───────────────────────┴───────────────────┐  │
│  │              Backtesting Engine                     │  │
│  │  - Historical Polymarket token prices               │  │
│  │  - Historical BTC candles from Binance              │  │
│  │  - Simulated order fills with fee modeling          │  │
│  └────────────────────────────────────────────────────┘  │
└──────────┬──────────────────────────┬────────────────────┘
           │                          │
    ┌──────┴──────┐          ┌────────┴────────┐
    │   Binance   │          │   Polymarket    │
    │   REST +    │          │   CLOB API +    │
    │   WebSocket │          │   WebSocket +   │
    │   (BTC      │          │   Gamma API     │
    │    candles)  │          │   (markets,     │
    │             │          │    orders,       │
    │             │          │    token prices) │
    └─────────────┘          └─────────────────┘
```

---

## Signal Architecture (Dual-Layer)

### Layer 1 — Polymarket Token TA
Analyze the Polymarket "Up" token price itself for momentum signals.

| Indicator | Parameters (tunable) | Signal |
|-----------|---------------------|--------|
| RSI | Period: 7-21 (default 14) | Oversold < 30 → buy Up, Overbought > 70 → buy Down |
| MACD | Fast: 12, Slow: 26, Signal: 9 | Crossover → direction change |
| Price momentum | Lookback: 3-10 candles | Accelerating price → trend continuation |

**Data source**: Polymarket CLOB price history endpoint + WebSocket live updates

### Layer 2 — BTC Price TA (Multi-Timeframe EMAs)
Analyze actual BTC price for directional bias.

| Timeframe | EMA Periods | Purpose |
|-----------|-------------|---------|
| 1-min | 5, 13 | Micro scalp signal |
| 5-min | 8, 21 | Short-term trend |
| 15-min | 9, 21, 55 | Primary trading timeframe |
| 1-hour | 12, 26 | Medium trend filter |
| 4-hour | 20, 50 | Macro trend bias |
| 1-day | 20, 50, 200 | Long-term trend context |

**Signal logic**: Count how many timeframes agree on direction. More alignment → higher conviction.

**Data source**: Binance REST API for historical candles + WebSocket for live 1-min updates

### Signal Combination
```
composite_score = (
    layer1_weight * polymarket_signal     # e.g., 0.4
  + layer2_weight * btc_ema_signal        # e.g., 0.6
)

if composite_score > buy_threshold:     → BUY "Up" token
if composite_score < -buy_threshold:    → BUY "Down" token
else:                                   → NO TRADE (sit out)
```

All weights and thresholds are tunable from the UI.

---

## Trading Engine

### Market Rotation
- Polymarket 15-min BTC markets rotate automatically
- Bot queries Gamma API for active BTC 15-min markets
- Detects when current market closes, switches to next
- Grace period: stop trading ~2 min before market close (configurable)

### Order Types
- **Primary**: GTC limit orders at or near best bid/ask
- **Aggressive**: FOK market orders when signal is very strong
- **postOnly**: For maker-only orders (avoids up to 3% taker fee)
- Strategy selectable from UI

### Risk Management (all configurable from UI)
| Parameter | Default | Range |
|-----------|---------|-------|
| Max position size | $3.00 | $1 - $100 |
| Max trades per 15-min window | 1 | 1-5 |
| Max daily loss | $15.00 | $5 - $500 |
| Min signal confidence | 0.6 | 0.1 - 1.0 |
| Stop trading after N consecutive losses | 3 | 1-10 |
| Cool-down period after stop | 30 min | 5-120 min |

### Fee Awareness
- Taker fees on 15-min markets: up to 3% (variable by probability)
- Prefer postOnly orders to earn maker rebates instead
- Fee impact calculated before every trade decision
- UI shows estimated fee drag on P&L

---

## Wallet Configuration

```python
# Magic/Email wallet setup
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,           # Exported from Polymarket settings
    chain_id=137,              # Polygon
    signature_type=1,          # Magic/email wallet
    funder=PROXY_ADDRESS       # Your Polymarket proxy wallet address
)
```

User provides:
1. **Private key** (exported from Settings → Advanced → Export Private Key)
2. **Proxy wallet address** (visible in Polymarket profile / deposit page)

These are stored in a `.env` file locally, never exposed to the frontend.

---

## Tech Stack

### Backend
- **Python 3.11+**
- **FastAPI** — REST API + WebSocket server
- **py-clob-client** — Polymarket CLOB integration
- **python-binance** or raw WebSocket — BTC price feeds
- **pandas + numpy** — TA calculations and backtesting
- **ta-lib or pandas-ta** — Technical indicator library
- **SQLite** — Local trade history, P&L, backtesting results
- **APScheduler** — Market rotation and periodic tasks

### Frontend
- **React 18** (Vite)
- **Recharts** — P&L charts, equity curves, indicator plots
- **TailwindCSS** — Styling
- **WebSocket client** — Real-time dashboard updates

---

## API Endpoints (Backend → Frontend)

### REST
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Bot status (running/stopped/error) |
| GET | `/api/market` | Current active 15-min market info |
| GET | `/api/positions` | Open positions and P&L |
| GET | `/api/trades` | Trade history |
| GET | `/api/signals` | Current signal state (both layers) |
| GET | `/api/config` | Current tunable parameters |
| PUT | `/api/config` | Update parameters (hot-reload) |
| POST | `/api/bot/start` | Start trading |
| POST | `/api/bot/stop` | Stop trading |
| POST | `/api/backtest` | Run backtest with given params |
| GET | `/api/backtest/{id}` | Get backtest results |

### WebSocket
| Channel | Data |
|---------|------|
| `/ws/dashboard` | Real-time P&L, signals, market data, trade events |

---

## Backtesting Engine

- Fetches historical BTC candles from Binance (configurable lookback)
- Fetches historical Polymarket token prices from CLOB price history API
- Simulates trades with realistic fill modeling:
  - Accounts for taker fees (up to 3%)
  - Accounts for spread (uses historical order book snapshots if available)
  - Slippage estimation based on trade size
- Outputs: equity curve, win rate, profit factor, max drawdown, Sharpe ratio
- Results displayed as interactive charts in the React UI

---

## Project Structure

```
polymarket-bot/
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Configuration management
│   ├── models.py               # Data models (Pydantic)
│   ├── database.py             # SQLite setup
│   ├── polymarket/
│   │   ├── client.py           # CLOB client wrapper
│   │   ├── markets.py          # Market discovery & rotation
│   │   └── orders.py           # Order placement & management
│   ├── binance/
│   │   ├── client.py           # Binance REST client
│   │   └── websocket.py        # Binance WebSocket for live candles
│   ├── signals/
│   │   ├── engine.py           # Signal combination logic
│   │   ├── polymarket_ta.py    # Layer 1: Token price TA
│   │   └── btc_ta.py           # Layer 2: BTC multi-TF EMAs
│   ├── trading/
│   │   ├── engine.py           # Main trading loop
│   │   └── risk.py             # Risk management
│   ├── backtest/
│   │   ├── engine.py           # Backtesting engine
│   │   └── metrics.py          # Performance metrics
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── Dashboard.jsx   # Live P&L, positions, market
│   │   │   ├── SignalPanel.jsx  # Current signals visualization
│   │   │   ├── ConfigPanel.jsx # Parameter tuning
│   │   │   ├── TradeHistory.jsx
│   │   │   ├── Backtester.jsx  # Backtest runner + results
│   │   │   └── Charts.jsx      # Recharts wrappers
│   │   └── hooks/
│   │       └── useWebSocket.js
│   ├── package.json
│   └── vite.config.js
├── .env                        # Private key, proxy address
└── README.md                   # Setup instructions
```

---

## Build Phases

### Phase 1 — Core Infrastructure
- [ ] Project scaffolding (backend + frontend)
- [ ] Polymarket client wrapper (market discovery, price fetching)
- [ ] Binance candle fetcher (REST + WebSocket)
- [ ] SQLite database for trade history
- [ ] FastAPI server with basic endpoints

### Phase 2 — Signal Engine
- [ ] Layer 1: Polymarket token TA (RSI, MACD)
- [ ] Layer 2: BTC multi-timeframe EMAs
- [ ] Signal combination with configurable weights
- [ ] Signal API endpoint + WebSocket broadcast

### Phase 3 — Trading Engine
- [ ] Automated order placement via CLOB API
- [ ] Market rotation (detect active 15-min market)
- [ ] Position tracking and P&L calculation
- [ ] Risk management (max loss, cooldowns, etc.)
- [ ] Fee-aware order type selection (postOnly vs market)

### Phase 4 — React Dashboard
- [ ] Live dashboard (P&L, positions, current market)
- [ ] Signal visualization (both layers)
- [ ] Parameter tuning panel with hot-reload
- [ ] Trade history table

### Phase 5 — Backtesting
- [ ] Historical data fetcher (Binance + Polymarket)
- [ ] Backtest simulation engine
- [ ] Performance metrics calculation
- [ ] Backtest UI with equity curves and stats

---

## Key Polymarket API Constraints

| Constraint | Detail | Our Approach |
|-----------|--------|--------------|
| Taker fees up to 3% | Variable by probability range on 15-min markets | Default to postOnly orders; show fee impact in UI |
| Rate limits | 3,500 POST /order per 10s burst; 1,500 /price per 10s | Generous for single bot; no special handling needed |
| Market rotation | 15-min markets close/open automatically | Poll Gamma API every ~60s for active markets |
| Token allowances | Must set USDC allowance for Exchange contract | Check on startup, prompt user if not set |
| Geographic | Canada is NOT restricted | No issues |
| WebSocket | User + Market channels for real-time updates | Use market channel for live token prices |
| Price history | Available via CLOB timeseries endpoint | Use for backtesting + initial TA warm-up |
| Batch orders | Up to 15 orders per request | Not needed for conservative single-trade strategy |

---

## Important Notes

1. **Start in DRY RUN mode** — Bot logs what it *would* trade without placing real orders. Switch to live from UI.
2. **Private key security** — Stored only in `.env`, never sent to frontend, never logged.
3. **15-min market lifecycle** — Each market has a specific condition_id and token_id. Bot must dynamically discover the current active market and its token IDs.
4. **Resolution** — Markets resolve based on Binance BTC price (Polymarket uses a specific price oracle). Understanding the exact resolution source helps calibrate signals.