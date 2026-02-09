"""
FastAPI server for the Polymarket BTC 15-min Trading Bot.

Provides REST endpoints for configuration and status,
plus a WebSocket for real-time dashboard updates.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from config import config_manager, API_HOST, API_PORT
from models import BotState, ConfigUpdateRequest
from trading.engine import trading_engine
from trading.risk import risk_manager
from trading.trade_logger import trade_logger
from signals.engine import signal_engine
from polymarket.markets import market_discovery
from polymarket.orders import order_manager
import database as db

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
    datefmt="%H:%M:%S",
)
# Silence verbose HTTP logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("=" * 60)
    logger.info("  Polymarket BTC 15-Min Trading Bot")
    logger.info(f"  Mode: {config_manager.config.mode}")
    logger.info(f"  API: http://{API_HOST}:{API_PORT}")
    logger.info(f"  Dashboard WS: ws://{API_HOST}:{API_PORT}/ws/dashboard")
    logger.info("=" * 60)
    db.init_db()
    yield
    # Shutdown
    if trading_engine.is_running:
        await trading_engine.stop()
    logger.info("Server shutting down")


# --- App ---
app = FastAPI(
    title="Polymarket BTC 15-Min Trading Bot",
    version="1.0.0",
    description="Automated directional trading bot for Polymarket BTC 15-minute prediction markets",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- WebSocket Manager ---
class ConnectionManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected ({len(self.active_connections)} total)")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket client disconnected ({len(self.active_connections)} total)")

    async def broadcast(self, data: dict):
        """Broadcast state to all connected clients."""
        if not self.active_connections:
            return

        message = json.dumps(data, default=str)
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            try:
                self.active_connections.remove(conn)
            except ValueError:
                pass


ws_manager = ConnectionManager()


# --- Wire up WebSocket broadcast to trading engine ---
async def broadcast_state(data: dict):
    await ws_manager.broadcast(data)

trading_engine.set_ws_broadcast(broadcast_state)


# --- Frontend static files ---
# Check if the built React app exists (from Docker multi-stage build)
_frontend_dist = Path(__file__).parent / "frontend" / "dist"

# --- REST Endpoints ---

if not _frontend_dist.exists():
    # No frontend build — redirect root to API docs (dev mode)
    @app.get("/", include_in_schema=False)
    async def root():
        """Redirect root to API docs."""
        return RedirectResponse(url="/docs")


@app.get("/api/status")
async def get_status():
    """Get bot status summary."""
    return {
        "status": trading_engine.status.value,
        "mode": config_manager.config.mode,
        "is_running": trading_engine.is_running,
        "risk": risk_manager.get_state(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market")
async def get_market():
    """Get current active 15-min market info."""
    market = market_discovery.current_market
    window_info = market_discovery.get_current_window_info()
    
    if not market:
        return {
            "active": False, 
            "market": None,
            "windows": window_info,
        }

    time_remaining = market_discovery.time_until_close()
    return {
        "active": True,
        "market": market.model_dump(),
        "time_remaining_seconds": time_remaining,
        "should_stop_trading": market_discovery.should_stop_trading(),
        "windows": window_info,
    }


@app.get("/api/positions")
async def get_positions():
    """Get open positions."""
    positions = order_manager.open_positions
    return {
        "positions": [p.model_dump() for p in positions],
        "count": len(positions),
    }


@app.get("/api/trades")
async def get_trades(limit: int = 50, offset: int = 0):
    """Get trade history."""
    trades = db.get_trades(limit=limit, offset=offset)
    return {
        "trades": [t.model_dump(mode="json") for t in trades],
        "count": len(trades),
    }


@app.get("/api/trades/export")
async def export_trades(include_incomplete: bool = True):
    """
    Export all trades with complete market state to JSON file.
    
    Args:
        include_incomplete: If True, includes trades without complete log data
    
    Returns:
        Export summary with file path
    """
    try:
        file_path = trade_logger.export_all_trades_to_json(
            include_incomplete=include_incomplete
        )
        summary = trade_logger.get_trade_summary()
        return {
            "success": True,
            "file_path": str(file_path),
            "summary": summary,
            "message": f"Trade log exported to {file_path}",
        }
    except Exception as e:
        logger.error(f"Error exporting trades: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trades/log-summary")
async def get_log_summary():
    """Get summary statistics about trade logs."""
    return trade_logger.get_trade_summary()


@app.get("/api/trades/{trade_id}/details")
async def get_trade_details(trade_id: int):
    """Get full trade details including market state snapshots."""
    trade = db.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    log_data_str = db.get_trade_log_data(trade_id)
    log_data = None
    if log_data_str:
        try:
            log_data = json.loads(log_data_str)
        except json.JSONDecodeError:
            log_data = None

    return {
        "trade": trade.model_dump(mode="json"),
        "log_data": log_data,
        "has_log_data": log_data is not None,
    }


@app.get("/api/sessions")
async def get_sessions(limit: int = 20, offset: int = 0):
    """Get list of past sessions."""
    sessions = db.get_sessions(limit=limit, offset=offset)
    return [s.model_dump() for s in sessions]


@app.get("/api/sessions/{session_id}")
async def get_session_details(session_id: int):
    """Get details for a specific session."""
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    stats = db.get_session_stats(session_id)
    trades = db.get_trades_for_session(session_id)
    
    return {
        "session": session.model_dump(),
        "stats": stats.model_dump(),
        "trades": [t.model_dump(mode="json") for t in trades],
    }


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: int):
    """
    Export a complete session as structured text optimized for AI consumption.

    Returns session overview, performance analytics, and full trade logs
    with market state data formatted for readability.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stats = db.get_session_stats(session_id)
    trades_with_logs = db.get_trades_with_log_data(session_id)

    # Compute analytics
    filled = [(t, ld) for t, ld in trades_with_logs if t.status.value == "filled"]
    wins = [(t, ld) for t, ld in filled if (t.pnl or 0) > 0]
    losses = [(t, ld) for t, ld in filled if (t.pnl or 0) < 0]

    avg_win = sum(t.pnl for t, _ in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl for t, _ in losses) / len(losses) if losses else 0.0
    profit_factor = abs(sum(t.pnl for t, _ in wins) / sum(t.pnl for t, _ in losses)) if losses and sum(t.pnl for t, _ in losses) != 0 else float("inf")
    total_fees = sum(t.fees for t, _ in filled)

    # Count exit reasons
    exit_reasons = {}
    for t, ld in filled:
        if ld:
            try:
                log = json.loads(ld)
                reason = log.get("exit_reason", "unknown")
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
            except Exception:
                pass

    analytics = {
        "total_trades": len(filled),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(filled) if filled else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "total_fees": round(total_fees, 2),
        "largest_win": round(stats.largest_win, 2),
        "largest_loss": round(stats.largest_loss, 2),
        "exit_reasons": exit_reasons,
    }

    # Build export text (include current bot config)
    current_config = config_manager.config.to_dict()
    export_text = _format_session_export(session, stats, analytics, trades_with_logs, current_config)

    return {
        "session": session.model_dump(),
        "stats": stats.model_dump(),
        "analytics": analytics,
        "export_text": export_text,
    }


def _format_session_export(session, stats, analytics, trades_with_logs, current_config=None) -> str:
    """Format a session as structured text for AI consumption."""
    lines = []
    now = datetime.now(timezone.utc).isoformat()

    # Header
    lines.append(f"# Session #{session.id} Export")
    lines.append(f"Generated: {now}")
    lines.append("")

    # Current Bot Configuration
    if current_config:
        lines.append("## Current Bot Configuration")
        lines.append(f"- Mode: {current_config.get('mode', 'N/A')}")
        lines.append("")

        sig = current_config.get("signal", {})
        if sig:
            lines.append("### Signal Settings")
            lines.append(f"- Layer 1 Weight: {sig.get('layer1_weight', 'N/A')}")
            lines.append(f"- Layer 2 Weight: {sig.get('layer2_weight', 'N/A')}")
            lines.append(f"- Buy Threshold: {sig.get('buy_threshold', 'N/A')}")
            lines.append(f"- RSI Period: {sig.get('pm_rsi_period', 'N/A')} (oversold={sig.get('pm_rsi_oversold', 'N/A')}, overbought={sig.get('pm_rsi_overbought', 'N/A')})")
            lines.append(f"- MACD: fast={sig.get('pm_macd_fast', 'N/A')} slow={sig.get('pm_macd_slow', 'N/A')} signal={sig.get('pm_macd_signal', 'N/A')}")
            lines.append(f"- Momentum Lookback: {sig.get('pm_momentum_lookback', 'N/A')}")
            btc_emas = []
            for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
                key = f"btc_ema_{tf}"
                if key in sig:
                    btc_emas.append(f"{tf}={sig[key]}")
            if btc_emas:
                lines.append(f"- BTC EMAs: {', '.join(btc_emas)}")
            lines.append("")

        risk = current_config.get("risk", {})
        if risk:
            lines.append("### Risk Settings")
            lines.append(f"- Max Position Size: ${risk.get('max_position_size', 'N/A')}")
            lines.append(f"- Max Trades/Window: {risk.get('max_trades_per_window', 'N/A')}")
            lines.append(f"- Max Daily Loss: ${risk.get('max_daily_loss', 'N/A')}")
            lines.append(f"- Min Signal Confidence: {risk.get('min_signal_confidence', 'N/A')}")
            lines.append(f"- Max Consecutive Losses: {risk.get('max_consecutive_losses', 'N/A')}")
            lines.append(f"- Cooldown: {risk.get('cooldown_minutes', 'N/A')} min")
            lines.append(f"- Stop Before Close: {risk.get('stop_trading_minutes_before_close', 'N/A')} min")
            lines.append(f"- Max Entry Price: {risk.get('max_entry_price', 'N/A')}")
            lines.append("")

        exit_cfg = current_config.get("exit", {})
        if exit_cfg:
            lines.append("### Exit Settings")
            lines.append(f"- Enabled: {exit_cfg.get('enabled', 'N/A')}")
            lines.append(f"- Trailing Stop: {exit_cfg.get('trailing_stop_pct', 'N/A')}")
            lines.append(f"- Hard Stop: {exit_cfg.get('hard_stop_pct', 'N/A')}")
            lines.append(f"- Signal Reversal Threshold: {exit_cfg.get('signal_reversal_threshold', 'N/A')}")
            lines.append(f"- Tighten At: {exit_cfg.get('tighten_at_seconds', 'N/A')}s (trailing={exit_cfg.get('tightened_trailing_pct', 'N/A')})")
            lines.append(f"- Final Zone: {exit_cfg.get('final_seconds', 'N/A')}s (trailing={exit_cfg.get('final_trailing_pct', 'N/A')})")
            lines.append(f"- Min Hold: {exit_cfg.get('min_hold_seconds', 'N/A')}s")
            lines.append(f"- Pressure Scaling: enabled={exit_cfg.get('pressure_scaling_enabled', 'N/A')} widen_max={exit_cfg.get('pressure_widen_max', 'N/A')} tighten_min={exit_cfg.get('pressure_tighten_min', 'N/A')} neutral={exit_cfg.get('pressure_neutral_zone', 'N/A')}")
            lines.append("")

        trading = current_config.get("trading", {})
        if trading:
            lines.append("### Trading Settings")
            lines.append(f"- Order Type: {trading.get('order_type', 'N/A')}")
            lines.append(f"- Price Offset: {trading.get('price_offset', 'N/A')}")
            lines.append(f"- FOK for Strong Signals: {trading.get('use_fok_for_strong_signals', 'N/A')} (threshold={trading.get('strong_signal_threshold', 'N/A')})")
            lines.append(f"- Poll Interval: {trading.get('poll_interval_seconds', 'N/A')}s")
            lines.append(f"- Market Discovery Interval: {trading.get('market_discovery_interval_seconds', 'N/A')}s")
            lines.append("")

    # Session Overview
    lines.append("## Session Overview")
    lines.append(f"- Start: {session.start_time.isoformat() if session.start_time else 'N/A'}")
    lines.append(f"- End: {session.end_time.isoformat() if session.end_time else 'ongoing'}")
    if session.start_time and session.end_time:
        duration = (session.end_time - session.start_time).total_seconds()
        mins, secs = divmod(int(duration), 60)
        hours, mins = divmod(mins, 60)
        lines.append(f"- Duration: {hours}h {mins}m {secs}s")
    lines.append(f"- Status: {session.status}")
    lines.append(f"- Total P&L: ${session.total_pnl or 0:.2f}")
    lines.append("")

    # Performance Summary
    lines.append("## Performance Summary")
    lines.append(f"- Trades: {analytics['total_trades']} ({analytics['wins']}W / {analytics['losses']}L)")
    lines.append(f"- Win Rate: {analytics['win_rate']:.1%}")
    lines.append(f"- Avg Win: ${analytics['avg_win']:.2f}")
    lines.append(f"- Avg Loss: ${analytics['avg_loss']:.2f}")
    pf = f"{analytics['profit_factor']:.2f}" if analytics['profit_factor'] is not None else "∞"
    lines.append(f"- Profit Factor: {pf}")
    lines.append(f"- Largest Win: ${analytics['largest_win']:.2f}")
    lines.append(f"- Largest Loss: ${analytics['largest_loss']:.2f}")
    lines.append(f"- Total Fees: ${analytics['total_fees']:.2f}")
    if analytics['exit_reasons']:
        lines.append(f"- Exit Reasons: {', '.join(f'{k}={v}' for k, v in analytics['exit_reasons'].items())}")
    lines.append("")

    # Trade Log
    lines.append("## Trade Log")
    for trade, log_data_str in trades_with_logs:
        if trade.status.value != "filled":
            continue

        pnl_str = f"${trade.pnl:+.2f}" if trade.pnl is not None else "pending"
        lines.append(f"### Trade #{trade.id} — {trade.side.value.upper()} @ ¢{trade.price * 100:.1f} → P&L: {pnl_str}")
        lines.append(f"- Time: {trade.timestamp.isoformat()}")
        lines.append(f"- Side: {trade.side.value.upper()}")
        lines.append(f"- Entry Price: ¢{trade.price * 100:.1f}")
        lines.append(f"- Size: {trade.size:.2f} tokens")
        lines.append(f"- Cost: ${trade.cost:.2f}")
        lines.append(f"- Fees: ${trade.fees:.2f}")
        lines.append(f"- Signal Score: {trade.signal_score:+.3f}")
        lines.append(f"- Dry Run: {'yes' if trade.is_dry_run else 'no'}")

        if log_data_str:
            try:
                log = json.loads(log_data_str)
            except Exception:
                log = {}

            # Exit metadata
            if log.get("exit_reason"):
                lines.append(f"- Exit Reason: {log['exit_reason']}")
            if log.get("exit_reason_detail"):
                lines.append(f"- Exit Detail: {log['exit_reason_detail']}")
            if log.get("exit_price") is not None:
                lines.append(f"- Exit Price: ¢{log['exit_price'] * 100:.1f}")
            if log.get("peak_price") is not None:
                lines.append(f"- Peak Price: ¢{log['peak_price'] * 100:.1f}")
            if log.get("drawdown_from_peak") is not None:
                lines.append(f"- Drawdown from Peak: {log['drawdown_from_peak']:.1%}")
            if log.get("position_held_duration_seconds") is not None:
                dur = int(log["position_held_duration_seconds"])
                lines.append(f"- Position Duration: {dur // 60}m {dur % 60}s")
            if log.get("time_remaining_at_exit") is not None:
                tr = log["time_remaining_at_exit"]
                if isinstance(tr, (int, float)):
                    lines.append(f"- Time Remaining at Exit: {int(tr) // 60}m {int(tr) % 60}s")

            # Buy state
            buy_state = log.get("buy_state", {})
            if buy_state:
                signal = buy_state.get("signal", {})
                if signal:
                    lines.append(f"- Entry Signal: composite={signal.get('composite_score', 0):+.3f}")
                    l1 = signal.get("layer1")
                    if l1:
                        rsi_val = l1.get("rsi", 0)
                        macd_val = l1.get("macd", 0)
                        momentum_val = l1.get("momentum", 0)
                        direction_val = l1.get("direction", 0)
                        confidence_val = l1.get("confidence", 0)
                        lines.append(
                            f"  - L1 (Polymarket TA): direction={direction_val:+.3f} | "
                            f"RSI={rsi_val:.1f} | MACD={macd_val:+.4f} | "
                            f"Momentum={momentum_val:+.4f} | conf={confidence_val:.2f}"
                        )
                    l2 = signal.get("layer2")
                    if l2:
                        direction_val = l2.get("direction", 0)
                        alignment = l2.get("alignment_count", 0)
                        total_tf = l2.get("total_timeframes", 6)
                        lines.append(f"  - L2 (BTC Multi-TF): direction={direction_val:+.3f} | alignment={alignment}/{total_tf}")
                        tfs = l2.get("timeframe_signals", {})
                        for tf_name, tf_val in tfs.items():
                            if isinstance(tf_val, (int, float)):
                                arrow = "↑" if tf_val > 0.1 else "↓" if tf_val < -0.1 else "—"
                                lines.append(f"    - {tf_name}: {tf_val:+.3f} {arrow}")

                btc_price = buy_state.get("btc_price")
                if btc_price:
                    lines.append(f"- BTC Price at Entry: ${btc_price:,.2f}")

                # Order book summary
                for book_key, label in [("orderbook_up", "UP Token"), ("orderbook_down", "DOWN Token")]:
                    ob = buy_state.get(book_key, {})
                    if ob:
                        bids = ob.get("bids", [])
                        asks = ob.get("asks", [])
                        bid_depth = sum(float(b.get("size", 0)) for b in bids[:5]) if bids else 0
                        ask_depth = sum(float(a.get("size", 0)) for a in asks[:5]) if asks else 0
                        best_bid = float(bids[0].get("price", 0)) if bids else 0
                        best_ask = float(asks[0].get("price", 0)) if asks else 0
                        lines.append(f"  - {label} Book: bid={best_bid:.3f} ask={best_ask:.3f} | depth: bid={bid_depth:.0f} ask={ask_depth:.0f}")

                # Risk state
                risk = buy_state.get("risk_state", {})
                if risk:
                    lines.append(f"- Risk State: consecutive_losses={risk.get('consecutive_losses', 0)} daily_pnl=${risk.get('daily_pnl', 0):.2f} trades_in_window={risk.get('trades_this_window', 0)}")

                # Market window
                mw = buy_state.get("market_window_info", {})
                if mw and mw.get("time_until_close_seconds") is not None:
                    tuc = int(mw["time_until_close_seconds"])
                    lines.append(f"- Time Until Close at Entry: {tuc // 60}m {tuc % 60}s")

                # Config snapshot
                config = buy_state.get("config_snapshot", {})
                if config:
                    lines.append(f"- Config: mode={config.get('mode', 'N/A')} order_type={config.get('trading', {}).get('order_type', 'N/A')} buy_threshold={config.get('signal', {}).get('buy_threshold', 'N/A')}")
                    exit_cfg = config.get("exit", {})
                    if exit_cfg:
                        lines.append(f"  - Exit: trailing={exit_cfg.get('trailing_stop_pct', 'N/A')} hard={exit_cfg.get('hard_stop_pct', 'N/A')} reversal={exit_cfg.get('signal_reversal_threshold', 'N/A')} pressure={exit_cfg.get('pressure_scaling_enabled', 'N/A')}")

            # Sell state (if different from buy)
            sell_state = log.get("sell_state", {})
            if sell_state:
                signal = sell_state.get("signal", {})
                if signal:
                    lines.append(f"- Exit Signal: composite={signal.get('composite_score', 0):+.3f}")
                btc_price = sell_state.get("btc_price")
                if btc_price:
                    lines.append(f"- BTC Price at Exit: ${btc_price:,.2f}")

            # BTC candles
            candles = buy_state.get("btc_candles_summary", {})
            if candles:
                candle_parts = []
                for tf, data in candles.items():
                    if isinstance(data, dict):
                        candle_parts.append(f"{tf}: O={data.get('open', 0):.0f} H={data.get('high', 0):.0f} L={data.get('low', 0):.0f} C={data.get('close', 0):.0f}")
                if candle_parts:
                    lines.append(f"- BTC Candles: {' | '.join(candle_parts)}")

        lines.append("")

    return "\n".join(lines)


@app.get("/api/signals")
async def get_signals():
    """Get current signal state."""
    signal = signal_engine.last_signal
    if signal:
        return signal.model_dump(mode="json")
    return {"message": "No signal computed yet"}


@app.get("/api/config")
async def get_config():
    """Get current bot configuration."""
    return config_manager.config.to_dict()


@app.put("/api/config")
async def update_config(request: ConfigUpdateRequest):
    """Update bot configuration (hot-reload)."""
    try:
        data = request.model_dump(exclude_none=True)
        updated = config_manager.update(data)
        logger.info(f"Configuration updated: {list(data.keys())}")
        return updated.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/bot/start")
async def start_bot():
    """Start the trading engine."""
    if trading_engine.is_running:
        return {"message": "Bot is already running", "status": trading_engine.status.value}

    await trading_engine.start()
    return {"message": "Bot started", "status": trading_engine.status.value}


@app.post("/api/bot/stop")
async def stop_bot():
    """Stop the trading engine."""
    if not trading_engine.is_running:
        return {"message": "Bot is already stopped", "status": trading_engine.status.value}

    await trading_engine.stop()
    return {"message": "Bot stopped", "status": trading_engine.status.value}


@app.get("/api/stats")
async def get_stats():
    """Get daily and overall statistics."""
    daily = db.get_daily_stats()
    state = trading_engine.get_state()
    return {
        "daily": daily.model_dump(),
        "total_pnl": state.total_pnl,
        "consecutive_losses": state.consecutive_losses,
    }


@app.get("/api/state")
async def get_full_state():
    """Get the complete bot state (dashboard payload)."""
    state = trading_engine.get_state()
    return state.model_dump(mode="json")


# --- WebSocket Endpoint ---

@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    WebSocket endpoint for real-time dashboard updates.
    Clients receive bot state every time the trading loop ticks.
    """
    await ws_manager.connect(websocket)
    try:
        # Send initial state
        state = trading_engine.get_state()
        await websocket.send_text(json.dumps(state.model_dump(mode="json"), default=str))

        # Keep connection alive and handle client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Handle ping/pong or client commands
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send periodic state update even without trading loop
                try:
                    state = trading_engine.get_state()
                    await websocket.send_text(
                        json.dumps(state.model_dump(mode="json"), default=str)
                    )
                except Exception:
                    break

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket error: {e}")
        try:
            ws_manager.disconnect(websocket)
        except ValueError:
            pass


# --- Static file serving (production) ---
# Mount AFTER all API/WS routes so /api/* and /ws/* take priority
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info(f"Serving frontend from {_frontend_dist}")


# --- Entry point ---
if __name__ == "__main__":
    import os
    # Disable bytecode caching to ensure fresh code is always loaded
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    
    import uvicorn
    uvicorn.run(
        app,  # Use direct app reference, not string import
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level="info",
        workers=1,  # Single worker to avoid multiprocessing reimport issues
    )
