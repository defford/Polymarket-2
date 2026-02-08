"""
SQLite database for persisting trades, P&L, and bot state.
"""

import os
import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from models import Trade, DailyStats, OrderStatus, Side, TradeLogEntry, Session

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent.parent / "bot_data.db"))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            market_condition_id TEXT NOT NULL,
            side TEXT NOT NULL,
            token_id TEXT NOT NULL,
            order_id TEXT,
            price REAL NOT NULL,
            size REAL NOT NULL,
            cost REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            pnl REAL,
            fees REAL DEFAULT 0.0,
            is_dry_run INTEGER DEFAULT 1,
            signal_score REAL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            trade_log_data TEXT
        );

        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            total_pnl REAL DEFAULT 0.0,
            fees_paid REAL DEFAULT 0.0,
            largest_win REAL DEFAULT 0.0,
            largest_loss REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            start_balance REAL,
            end_balance REAL,
            total_pnl REAL DEFAULT 0.0,
            status TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
        CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market_condition_id);
        CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    """)
    
    # Migration: Add trade_log_data column if it doesn't exist
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN trade_log_data TEXT")
    except sqlite3.OperationalError:
        pass

    # Migration: Add session_id column if it doesn't exist
    try:
        conn.execute("ALTER TABLE trades ADD COLUMN session_id INTEGER")
    except sqlite3.OperationalError:
        pass
    
    # Create index for session_id after column exists
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_session ON trades(session_id)")
    
    conn.commit()
    conn.close()


# --- Session Operations ---

def create_session(session: Session) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO sessions
           (start_time, start_balance, total_pnl, status)
           VALUES (?, ?, ?, ?)""",
        (
            session.start_time.isoformat(),
            session.start_balance,
            session.total_pnl,
            session.status,
        ),
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id


def update_session(session_id: int, **kwargs):
    conn = get_connection()
    # Handle datetime serialization if present in kwargs
    if "end_time" in kwargs and isinstance(kwargs["end_time"], datetime):
        kwargs["end_time"] = kwargs["end_time"].isoformat()
        
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [session_id]
    conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_sessions(limit: int = 20, offset: int = 0) -> list[Session]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [_row_to_session(r) for r in rows]


def get_session(session_id: int) -> Optional[Session]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if row:
        return _row_to_session(row)
    return None


def get_trade(trade_id: int) -> Optional[Trade]:
    """Get a single trade by ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM trades WHERE id = ?",
        (trade_id,),
    ).fetchone()
    conn.close()
    if row:
        return _row_to_trade(row)
    return None


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        start_time=datetime.fromisoformat(row["start_time"]),
        end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
        start_balance=row["start_balance"],
        end_balance=row["end_balance"],
        total_pnl=row["total_pnl"],
        status=row["status"],
    )


# --- Trade Operations ---

def insert_trade(trade: Trade, trade_log_data: Optional[str] = None) -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO trades
           (timestamp, market_condition_id, side, token_id, order_id,
            price, size, cost, status, pnl, fees, is_dry_run, signal_score, notes, trade_log_data, session_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade.timestamp.isoformat(),
            trade.market_condition_id,
            trade.side.value,
            trade.token_id,
            trade.order_id,
            trade.price,
            trade.size,
            trade.cost,
            trade.status.value,
            trade.pnl,
            trade.fees,
            1 if trade.is_dry_run else 0,
            trade.signal_score,
            trade.notes,
            trade_log_data,
            trade.session_id,
        ),
    )
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id


def update_trade(trade_id: int, **kwargs):
    conn = get_connection()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [trade_id]
    conn.execute(f"UPDATE trades SET {sets} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_trades(limit: int = 50, offset: int = 0) -> list[Trade]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def get_all_trades() -> list[Trade]:
    """Get all trades from the database."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def get_trade_log_data(trade_id: int) -> Optional[str]:
    """Get trade log data for a specific trade."""
    conn = get_connection()
    row = conn.execute(
        "SELECT trade_log_data FROM trades WHERE id = ?",
        (trade_id,),
    ).fetchone()
    conn.close()
    if row and row["trade_log_data"]:
        return row["trade_log_data"]
    return None


def get_trades_for_market(condition_id: str) -> list[Trade]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE market_condition_id = ? ORDER BY timestamp",
        (condition_id,),
    ).fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def get_trades_for_session(session_id: int) -> list[Trade]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE session_id = ? ORDER BY timestamp DESC",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def get_trades_with_log_data(session_id: int) -> list[tuple[Trade, Optional[str]]]:
    """Get all trades for a session with their log data in one query.

    Returns list of (Trade, raw_json_string) tuples. Avoids N+1 queries
    when building session exports.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        trade = _row_to_trade(row)
        log_data = row["trade_log_data"] if "trade_log_data" in row.keys() else None
        results.append((trade, log_data))
    return results


def get_today_trades() -> list[Trade]:
    today = date.today().isoformat()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE timestamp >= ? ORDER BY timestamp",
        (today,),
    ).fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def _row_to_trade(row: sqlite3.Row) -> Trade:
    return Trade(
        id=row["id"],
        session_id=row["session_id"] if "session_id" in row.keys() else None,
        timestamp=datetime.fromisoformat(row["timestamp"]),
        market_condition_id=row["market_condition_id"],
        side=Side(row["side"]),
        token_id=row["token_id"],
        order_id=row["order_id"],
        price=row["price"],
        size=row["size"],
        cost=row["cost"],
        status=OrderStatus(row["status"]),
        pnl=row["pnl"],
        fees=row["fees"],
        is_dry_run=bool(row["is_dry_run"]),
        signal_score=row["signal_score"],
        notes=row["notes"] or "",
    )


# --- Daily/Session Stats ---

def get_session_stats(session_id: int) -> DailyStats:
    """Calculate stats for a specific session."""
    trades = get_trades_for_session(session_id)
    
    filled = [t for t in trades if t.status == OrderStatus.FILLED]
    winners = [t for t in filled if (t.pnl or 0) > 0]
    losers = [t for t in filled if (t.pnl or 0) < 0]
    total_pnl = sum(t.pnl or 0 for t in filled)
    fees = sum(t.fees for t in filled)

    return DailyStats(
        date=f"Session {session_id}",
        total_trades=len(filled),
        winning_trades=len(winners),
        losing_trades=len(losers),
        total_pnl=total_pnl,
        fees_paid=fees,
        win_rate=len(winners) / len(filled) if filled else 0.0,
        largest_win=max((t.pnl or 0 for t in filled), default=0.0),
        largest_loss=min((t.pnl or 0 for t in filled), default=0.0),
    )


def get_daily_stats(target_date: Optional[str] = None) -> DailyStats:
    if target_date is None:
        target_date = date.today().isoformat()

    trades = get_today_trades() if target_date == date.today().isoformat() else []

    if not trades:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (target_date,)
        ).fetchone()
        conn.close()
        if row:
            return DailyStats(
                date=row["date"],
                total_trades=row["total_trades"],
                winning_trades=row["winning_trades"],
                losing_trades=row["losing_trades"],
                total_pnl=row["total_pnl"],
                fees_paid=row["fees_paid"],
                largest_win=row["largest_win"],
                largest_loss=row["largest_loss"],
                win_rate=(
                    row["winning_trades"] / row["total_trades"]
                    if row["total_trades"] > 0
                    else 0.0
                ),
            )
        return DailyStats(date=target_date)

    filled = [t for t in trades if t.status == OrderStatus.FILLED]
    winners = [t for t in filled if (t.pnl or 0) > 0]
    losers = [t for t in filled if (t.pnl or 0) < 0]
    total_pnl = sum(t.pnl or 0 for t in filled)
    fees = sum(t.fees for t in filled)

    return DailyStats(
        date=target_date,
        total_trades=len(filled),
        winning_trades=len(winners),
        losing_trades=len(losers),
        total_pnl=total_pnl,
        fees_paid=fees,
        win_rate=len(winners) / len(filled) if filled else 0.0,
        largest_win=max((t.pnl or 0 for t in filled), default=0.0),
        largest_loss=min((t.pnl or 0 for t in filled), default=0.0),
    )


# --- Bot State KV Store ---

def set_state(key: str, value):
    conn = get_connection()
    conn.execute(
        """INSERT INTO bot_state (key, value, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
        (key, json.dumps(value), datetime.utcnow().isoformat(),
         json.dumps(value), datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_state(key: str, default=None):
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM bot_state WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if row:
        return json.loads(row["value"])
    return default


# Initialize on import
init_db()
