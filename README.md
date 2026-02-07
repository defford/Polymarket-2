# Polymarket BTC 15-Min Trading Bot

Automated directional trading bot for Polymarket's BTC 15-minute Up/Down prediction markets.

## Architecture

The bot uses a **dual-layer signal system**:

- **Layer 1 — Polymarket Token TA**: RSI, MACD, and momentum on the "Up" token price itself (market sentiment)
- **Layer 2 — BTC Price TA**: Multi-timeframe EMA analysis on real BTC/USDT candles from Binance (1m, 5m, 15m, 1h, 4h, 1d)

Signals are combined with configurable weights to produce a composite score. When the score exceeds the threshold and risk checks pass, the bot trades.

## Features

- ✅ Fully automated market rotation (detects new 15-min windows)
- ✅ Dry-run mode (default) — simulates trades without real money
- ✅ Configurable risk management (position size, daily loss limit, cooldowns)
- ✅ Fee-aware ordering (defaults to postOnly to avoid 3% taker fees)
- ✅ REST API for dashboard integration
- ✅ WebSocket for real-time updates
- ✅ SQLite trade history and P&L tracking
- ✅ Hot-reloadable configuration

## Quick Start

### 1. Prerequisites

- Python 3.11+ (recommended: 3.12)
- A Polymarket account funded with USDC on Polygon
- macOS (developed for Mac, works on Linux too)

### 2. Clone and Install

```bash
cd polymarket-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
cd backend
pip install -r requirements.txt
```

### 3. Configure

```bash
# Copy the example env file
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
# REQUIRED for live trading (not needed for dry-run with simulated data)
POLYMARKET_PRIVATE_KEY=your_private_key_here
POLYMARKET_PROXY_ADDRESS=your_proxy_wallet_address_here

# Start in dry-run mode (STRONGLY RECOMMENDED)
BOT_MODE=dry_run
```

**How to get your private key:**
1. Go to [polymarket.com](https://polymarket.com)
2. Click your profile → Settings → Advanced
3. Click "Export Private Key"
4. Copy the key into `.env`

**How to get your proxy address:**
1. Go to your Polymarket deposit page
2. Your proxy wallet address is shown there (starts with 0x...)

### 4. Run

```bash
cd backend
python main.py
```

The bot starts a FastAPI server at `http://127.0.0.1:8000`.

### 5. Start Trading

The bot does NOT auto-start trading. You must explicitly start it:

```bash
# Start the bot (dry-run mode)
curl -X POST http://127.0.0.1:8000/api/bot/start

# Check status
curl http://127.0.0.1:8000/api/status

# View current signal
curl http://127.0.0.1:8000/api/signals

# View trades
curl http://127.0.0.1:8000/api/trades

# Get full state (what the dashboard will show)
curl http://127.0.0.1:8000/api/state

# Stop the bot
curl -X POST http://127.0.0.1:8000/api/bot/stop
```

### 6. Tune Parameters

```bash
# Update signal weights (make BTC EMAs more important)
curl -X PUT http://127.0.0.1:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"signal": {"layer1_weight": 0.3, "layer2_weight": 0.7}}'

# Increase position size
curl -X PUT http://127.0.0.1:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"risk": {"max_position_size": 5.0}}'

# Switch to live mode (CAUTION: real money!)
curl -X PUT http://127.0.0.1:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"mode": "live"}'
```

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/status` | Bot status and risk state |
| GET | `/api/market` | Current active 15-min market |
| GET | `/api/positions` | Open positions |
| GET | `/api/trades` | Trade history |
| GET | `/api/signals` | Current signal values |
| GET | `/api/config` | Current configuration |
| PUT | `/api/config` | Update configuration |
| GET | `/api/stats` | Daily and total statistics |
| GET | `/api/state` | Full dashboard state |
| POST | `/api/bot/start` | Start trading |
| POST | `/api/bot/stop` | Stop trading |
| WS | `/ws/dashboard` | Real-time state updates |

## Configuration

All parameters are tunable via the API (and will be tunable from the React dashboard in Phase 4).

### Signal Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `layer1_weight` | 0.4 | Weight for Polymarket token TA |
| `layer2_weight` | 0.6 | Weight for BTC EMA signals |
| `buy_threshold` | 0.3 | Min composite score to trade |
| `pm_rsi_period` | 14 | RSI period for token TA |
| `pm_rsi_oversold` | 30 | RSI oversold level |
| `pm_rsi_overbought` | 70 | RSI overbought level |

### Risk Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_size` | $3.00 | Max USDC per trade |
| `max_trades_per_window` | 1 | Max trades per 15-min market |
| `max_daily_loss` | $15.00 | Daily loss limit |
| `min_signal_confidence` | 0.6 | Min confidence to trade |
| `max_consecutive_losses` | 3 | Losses before cooldown |
| `cooldown_minutes` | 30 | Cooldown duration |

### Trading Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| `order_type` | postOnly | Order type (postOnly/limit/market) |
| `price_offset` | 0.01 | Offset from best price |
| `poll_interval_seconds` | 10 | Signal check frequency |

## Project Structure

```
polymarket-bot/
├── backend/
│   ├── main.py              # FastAPI server + endpoints
│   ├── config.py            # Configuration management
│   ├── models.py            # Data models
│   ├── database.py          # SQLite persistence
│   ├── polymarket/
│   │   ├── client.py        # CLOB API wrapper
│   │   ├── markets.py       # Market discovery & rotation
│   │   └── orders.py        # Order management
│   ├── binance/
│   │   └── client.py        # BTC candle data
│   ├── signals/
│   │   ├── engine.py        # Signal combination
│   │   ├── polymarket_ta.py # Layer 1: Token TA
│   │   └── btc_ta.py        # Layer 2: BTC EMAs
│   └── trading/
│       ├── engine.py        # Main trading loop
│       └── risk.py          # Risk management
├── .env                     # Your credentials (not in git!)
├── .env.example             # Template
└── README.md
```

## Safety Notes

1. **Always start in dry-run mode.** The bot defaults to this.
2. **Never share your private key.** It's stored only in `.env` locally.
3. **The 15-min markets have up to 3% taker fees.** The bot defaults to `postOnly` orders to avoid these.
4. **Start conservative.** The default $3 position size is intentional for learning.
5. **Monitor the bot.** Check in periodically even in automated mode.

## Next Steps (Phase 4 & 5)

- React dashboard with live P&L, signal visualization, and parameter tuning
- Backtesting engine with historical data from Binance + Polymarket
- Equity curves and performance metrics
