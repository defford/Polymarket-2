"""
Configuration management for the trading bot.
All tunable parameters live here with sensible defaults.
Parameters can be hot-reloaded from the API.
"""

import os
import json
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


# --- Environment (secrets, not tunable from UI) ---

POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_PROXY_ADDRESS = os.getenv("POLYMARKET_PROXY_ADDRESS", "")
POLYMARKET_CLOB_HOST = os.getenv("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com")
POLYMARKET_GAMMA_HOST = os.getenv("POLYMARKET_GAMMA_HOST", "https://gamma-api.polymarket.com")
POLYMARKET_WS_HOST = os.getenv("POLYMARKET_WS_HOST", "wss://ws-subscriptions-clob.polymarket.com")
CHAIN_ID = int(os.getenv("CHAIN_ID", "137"))
BINANCE_SYMBOL = os.getenv("BINANCE_SYMBOL", "BTCUSDT")
BOT_MODE = os.getenv("BOT_MODE", "dry_run")  # "dry_run" or "live"
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))


# --- Tunable Parameters (adjustable from UI) ---

@dataclass
class SignalConfig:
    """Layer 1 & 2 signal parameters."""

    # Layer 1: Polymarket token TA
    pm_rsi_period: int = 14
    pm_rsi_oversold: float = 30.0
    pm_rsi_overbought: float = 70.0
    pm_macd_fast: int = 12
    pm_macd_slow: int = 26
    pm_macd_signal: int = 9
    pm_momentum_lookback: int = 5

    # Layer 2: BTC multi-timeframe EMAs
    btc_ema_1m: list = field(default_factory=lambda: [5, 13])
    btc_ema_5m: list = field(default_factory=lambda: [8, 21])
    btc_ema_15m: list = field(default_factory=lambda: [9, 21, 55])
    btc_ema_1h: list = field(default_factory=lambda: [12, 26])
    btc_ema_4h: list = field(default_factory=lambda: [20, 50])
    btc_ema_1d: list = field(default_factory=lambda: [20, 50, 200])

    # Signal combination weights
    layer1_weight: float = 0.7
    layer2_weight: float = 0.3
    buy_threshold: float = 0.25  # composite score must exceed this to trade

    # VWAP (Volume Weighted Average Price) — toggle for A/B testing
    vwap_enabled: bool = False          # when ON, blends VWAP direction into composite score
    vwap_weight: float = 0.15           # weight when enabled (L1+L2+VWAP normalize to 1.0)
    vwap_session_reset_hour_utc: int = 0  # hour (0-23) to reset the VWAP session

    # VROC (Volume Rate of Change) — toggle for A/B testing
    vroc_enabled: bool = False           # when ON, gates trades by volume confirmation
    vroc_lookback: int = 10              # number of 15m candles for the rolling average
    vroc_threshold: float = 50.0         # minimum VROC% to confirm breakout volume
    vroc_confidence_penalty: float = 0.5 # multiply confidence by this when VROC is below threshold

    # Signal quality filters
    min_l2_alignment: int = 4            # require at least 4/6 BTC timeframes aligned
    require_layer_agreement: bool = True # L1 and L2 must agree on direction


@dataclass
class RiskConfig:
    """Risk management parameters."""

    max_position_size: float = 3.0       # USD per trade
    max_trades_per_window: int = 3       # per 15-min market
    max_daily_loss: float = 15.0         # USD
    min_signal_confidence: float = 0.50  # 0.0 - 1.0 (raised from 0.45)
    max_consecutive_losses: int = 3
    cooldown_minutes: int = 30           # after hitting loss limit
    stop_trading_minutes_before_close: int = 5  # stop before market closes
    min_entry_price: float = 0.25        # min price to buy (avoid volatile low-price tokens)
    max_entry_price: float = 0.75        # max price to pay for a contract (0.0-1.0)


@dataclass
class ExitConfig:
    """Position exit / stop-loss parameters."""

    enabled: bool = True                    # master switch for exit strategy
    trailing_stop_pct: float = 0.20         # sell if price drops 20% from peak
    hard_stop_pct: float = 0.20             # sell if price drops 20% from entry (absolute floor)
    signal_reversal_threshold: float = 0.15 # exit if composite flips this far against us
    tighten_at_seconds: int = 240           # tighten trailing stop in final 4 minutes
    tightened_trailing_pct: float = 0.10    # trailing stop when time is running out
    final_seconds: int = 90                 # ultra-tight zone in final 90 seconds
    final_trailing_pct: float = 0.03        # trailing stop in final seconds
    min_hold_seconds: int = 20              # don't exit in the first 20s (avoid noise)

    # BTC pressure scaling — short-term TA adjusts stop width
    pressure_scaling_enabled: bool = True
    pressure_widen_max: float = 1.5         # max multiplier when BTC supports position
    pressure_tighten_min: float = 0.4       # min multiplier when BTC is against position
    pressure_neutral_zone: float = 0.15     # pressure below this = no adjustment

    # Take Profit
    hard_tp_enabled: bool = True            # master switch for hard take-profit
    hard_tp_pct: float = 0.25               # exit when price rises 25% from entry
    scaling_tp_enabled: bool = False          # master switch for scaling take-profit
    scaling_tp_pct: float = 0.50             # fraction of gain used to tighten trailing stop
    scaling_tp_min_trail: float = 0.02       # floor: trailing stop can never go below 2%

    # Survival Buffer — initial protection window
    survival_buffer_enabled: bool = True     # master switch for survival buffer
    survival_buffer_seconds: int = 180       # first 180s: hard stop only, no trailing
    survival_hard_stop_bps: float = 1000.0     # 1000 BPS (10%) hard stop during buffer

    # Dynamic Conviction Scaling
    high_conviction_threshold: float = 0.45  # conviction > this = extended TP
    high_conviction_tp_pct: float = 0.35     # higher TP for high-conviction trades
    low_conviction_threshold: float = 0.25   # conviction < this = tighten exits
    low_conviction_trail_pct: float = 0.001  # 0.1% trail for low-conviction positions

    # Divergence Monitor — detect token noise vs legitimate BTC signal
    divergence_monitor_enabled: bool = True
    token_noise_threshold_bps: float = 10.0   # Token must drop > this BPS
    btc_stable_threshold_bps: float = 2.0     # BTC must move < this BPS to classify as noise

    # Signal Decay E-Stop — emergency exit when BTC conviction collapses
    signal_decay_estop_enabled: bool = True
    signal_decay_threshold: float = 0.15      # L2 confidence below this = immediate exit

    # Liquidity Guard — prevent stop-hunts during illiquid conditions
    liquidity_guard_enabled: bool = True
    token_wide_spread_bps: float = 3000.0     # Token spread > this = potential stop-hunt
    btc_spread_stable_bps: float = 500.0      # BTC spread change < this = stable

    # Delta Scaling — ATR-based TP adjustment
    delta_scaling_enabled: bool = True
    atr_base_tp_pct: float = 0.25             # Base TP at median ATR
    atr_scale_factor: float = 0.5             # TP adjustment per ATR std dev
    atr_reference_window: int = 100           # Periods for ATR percentile calculation

    # ATR-Based Stop Loss
    atr_stop_enabled: bool = True             # Use ATR for dynamic stop loss
    atr_stop_multiplier: float = 2.0          # Stop at 2x ATR from entry
    atr_stop_min_pct: float = 0.08            # Minimum 8% stop
    atr_stop_max_pct: float = 0.18            # Maximum 18% stop

    # Profit-Scaled Trailing Stop
    profit_scaled_trailing_enabled: bool = True  # Widen trailing as profits grow
    profit_trail_at_15pct: float = 0.18       # Use 18% trail at 15% gain
    profit_trail_at_30pct: float = 0.22       # Use 22% trail at 30% gain
    profit_trail_at_50pct: float = 0.28       # Use 28% trail at 50% gain


@dataclass
class TradingConfig:
    """Trading behavior parameters."""

    order_type: str = "postOnly"  # "postOnly", "limit", "market"
    price_offset: float = 0.01   # offset from best price for limit orders
    use_fok_for_strong_signals: bool = False
    strong_signal_threshold: float = 0.8  # when to use FOK
    poll_interval_seconds: int = 10  # how often to check signals
    market_discovery_interval_seconds: int = 30  # how often to scan for new markets
    max_order_retries: int = 30  # how many seconds to wait for a fill before cancelling


@dataclass
class BayesianConfig:
    """Bayesian signal weighting parameters."""
    
    enabled: bool = True
    rolling_window: int = 100
    min_sample_size: int = 50
    default_confidence: float = 0.5
    confidence_threshold: float = 0.4
    smoothing_alpha: float = 0.1


@dataclass
class BotConfig:
    """Top-level bot configuration."""

    signal: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    exit: ExitConfig = field(default_factory=ExitConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    bayesian: BayesianConfig = field(default_factory=BayesianConfig)
    mode: str = "dry_run"  # "dry_run" or "live"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BotConfig":
        return cls(
            signal=SignalConfig(**data.get("signal", {})),
            risk=RiskConfig(**data.get("risk", {})),
            exit=ExitConfig(**data.get("exit", {})),
            trading=TradingConfig(**data.get("trading", {})),
            bayesian=BayesianConfig(**data.get("bayesian", {})),
            mode=data.get("mode", "dry_run"),
        )


class ConfigManager:
    """
    Thread-safe config manager that supports hot-reload from the API.
    Persists to a JSON file so settings survive restarts.
    """

    CONFIG_FILE = Path(os.environ.get(
        "CONFIG_FILE",
        Path(__file__).parent.parent / "bot_config.json",
    ))

    def __init__(self):
        self._lock = threading.Lock()
        self._config = self._load()

    def _load(self) -> BotConfig:
        if self.CONFIG_FILE.exists():
            try:
                with open(self.CONFIG_FILE) as f:
                    data = json.load(f)
                return BotConfig.from_dict(data)
            except Exception:
                pass
        config = BotConfig(mode=BOT_MODE)
        self._save(config)
        return config

    def _save(self, config: BotConfig):
        with open(self.CONFIG_FILE, "w") as f:
            json.dump(config.to_dict(), f, indent=2)

    @property
    def config(self) -> BotConfig:
        with self._lock:
            return self._config

    def update(self, data: dict) -> BotConfig:
        with self._lock:
            merged = self._config.to_dict()
            for key, value in data.items():
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
            self._config = BotConfig.from_dict(merged)
            self._save(self._config)
            return self._config


# Global singleton
config_manager = ConfigManager()
