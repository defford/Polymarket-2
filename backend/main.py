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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

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


# --- REST Endpoints ---

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
