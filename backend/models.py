"""
Data models shared across the application.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel


class BotStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    DRY_RUN = "dry_run"
    ERROR = "error"
    COOLDOWN = "cooldown"


class Side(str, Enum):
    UP = "up"
    DOWN = "down"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Session(BaseModel):
    """A single bot run session."""
    id: Optional[int] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    start_balance: Optional[float] = None
    end_balance: Optional[float] = None
    total_pnl: float = 0.0
    status: str = "running"


# --- Market Models ---

class MarketInfo(BaseModel):
    """Active Polymarket 15-min BTC market."""
    condition_id: str
    question: str
    up_token_id: str
    down_token_id: str
    up_price: float = 0.5
    down_price: float = 0.5
    end_time: Optional[datetime] = None
    market_slug: Optional[str] = None
    active: bool = True


class OrderBookLevel(BaseModel):
    price: float
    size: float


class OrderBookSnapshot(BaseModel):
    up_bids: list[OrderBookLevel] = []
    up_asks: list[OrderBookLevel] = []
    down_bids: list[OrderBookLevel] = []
    down_asks: list[OrderBookLevel] = []
    timestamp: datetime = None


# --- Signal Models ---

class Layer1Signal(BaseModel):
    """Polymarket token TA signal."""
    rsi: Optional[float] = None
    macd: Optional[float] = None
    macd_signal_line: Optional[float] = None
    macd_histogram: Optional[float] = None
    momentum: Optional[float] = None
    direction: float = 0.0  # -1 to +1 (negative = DOWN, positive = UP)
    confidence: float = 0.0  # 0 to 1


class Layer2Signal(BaseModel):
    """BTC price multi-timeframe EMA signal."""
    timeframe_signals: dict[str, float] = {}  # e.g. {"1m": 1.0, "5m": -1.0, ...}
    alignment_count: int = 0  # how many TFs agree
    total_timeframes: int = 6
    direction: float = 0.0  # -1 to +1
    confidence: float = 0.0  # 0 to 1


class CompositeSignal(BaseModel):
    """Combined signal from both layers."""
    layer1: Layer1Signal = Layer1Signal()
    layer2: Layer2Signal = Layer2Signal()
    composite_score: float = 0.0  # -1 to +1
    composite_confidence: float = 0.0  # 0 to 1
    recommended_side: Optional[Side] = None
    should_trade: bool = False
    timestamp: datetime = None


# --- Trade Models ---

class Trade(BaseModel):
    """A completed or pending trade."""
    id: Optional[int] = None
    session_id: Optional[int] = None
    timestamp: datetime
    market_condition_id: str
    side: Side
    token_id: str
    order_id: Optional[str] = None
    price: float
    size: float  # in tokens
    cost: float  # in USDC
    status: OrderStatus = OrderStatus.PENDING
    pnl: Optional[float] = None
    fees: float = 0.0
    is_dry_run: bool = True
    signal_score: float = 0.0
    notes: str = ""


class Position(BaseModel):
    """Current open position."""
    market_condition_id: str
    side: Side
    token_id: str
    entry_price: float
    size: float
    cost: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    peak_price: float = 0.0       # highest price since entry (for trailing stop)
    entry_time: Optional[datetime] = None  # when we entered
    is_dry_run: bool = True


# --- Snapshot Models ---

class MarketStateSnapshot(BaseModel):
    """
    Capture complete market state snapshot at a point in time.
    Includes market info, signals, orderbooks, BTC data, risk state, and config.
    """
    timestamp: datetime
    market: MarketInfo
    signal: CompositeSignal
    orderbook_up: Dict[str, Any] = {}
    orderbook_down: Dict[str, Any] = {}
    btc_price: Optional[float] = None
    btc_candles_summary: Dict[str, Any] = {}
    risk_state: Dict[str, Any] = {}
    config_snapshot: Dict[str, Any] = {}
    market_window_info: Dict[str, Any] = {}


class TradeLogEntry(BaseModel):
    """
    Wrapper for trade log data.
    """
    trade_id: int
    log_data: str


# --- Dashboard Models ---

class DailyStats(BaseModel):
    date: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    fees_paid: float = 0.0
    win_rate: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0


class BotState(BaseModel):
    """Full bot state for the dashboard."""
    status: BotStatus = BotStatus.STOPPED
    mode: str = "dry_run"
    current_market: Optional[MarketInfo] = None
    current_signal: Optional[CompositeSignal] = None
    open_positions: list[Position] = []
    recent_trades: list[Trade] = []
    daily_stats: DailyStats = DailyStats(date="")
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    usdc_balance: Optional[float] = None
    last_updated: Optional[datetime] = None


# --- API Request/Response Models ---

class ConfigUpdateRequest(BaseModel):
    signal: Optional[dict] = None
    risk: Optional[dict] = None
    trading: Optional[dict] = None
    exit: Optional[dict] = None
    mode: Optional[str] = None


class BacktestRequest(BaseModel):
    start_date: str  # ISO format
    end_date: str
    config_override: Optional[dict] = None


# --- Swarm Models ---

class BotRecord(BaseModel):
    """Persisted bot definition for the swarm."""
    id: Optional[int] = None
    name: str
    description: str = ""
    config_json: str = "{}"  # serialized BotConfig
    mode: str = "dry_run"
    status: str = "stopped"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateBotRequest(BaseModel):
    name: str
    description: str = ""
    config: Optional[dict] = None  # full BotConfig dict
    clone_from: Optional[int] = None  # bot_id to clone config from


class UpdateBotRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
