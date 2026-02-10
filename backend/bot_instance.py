"""
BotInstance and BotConfigManager.

Each BotInstance encapsulates all per-bot state: its own engine,
signal engine, risk manager, order manager, market discovery,
and market stream.  Per-bot PolymarketClient instances and a shared
read-only BinanceClient are injected by the SwarmManager.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from config import BotConfig
from models import BotState
import database as db

logger = logging.getLogger(__name__)


class BotConfigManager:
    """Per-bot config manager.  Stores in-memory, persisted to DB by caller."""

    def __init__(self, initial_config: BotConfig):
        self._lock = threading.Lock()
        self._config = initial_config

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
            return self._config


class BotInstance:
    """Encapsulates all state for a single trading bot."""

    def __init__(
        self,
        bot_id: int,
        name: str,
        config: BotConfig,
        description: str = "",
        polymarket_client=None,
        binance_client=None,
    ):
        self.bot_id = bot_id
        self.name = name
        self.description = description

        # Per-bot config manager (in-memory, DB-persisted)
        self.config_manager = BotConfigManager(config)

        # Injected clients (PolymarketClient is per-bot; BinanceClient is shared read-only)
        self._polymarket_client = polymarket_client
        self._binance_client = binance_client

        # Per-bot instances — lazy-created so shared clients are set first
        self._signal_engine = None
        self._risk_manager = None
        self._order_manager = None
        self._market_discovery = None
        self._market_stream = None
        self._trading_engine = None

    def _ensure_components(self):
        """Create per-bot component instances (called once before start)."""
        if self._trading_engine is not None:
            return

        from signals.engine import SignalEngine
        from trading.risk import RiskManager
        from polymarket.orders import OrderManager
        from polymarket.markets import MarketDiscovery
        from polymarket.stream import MarketDataStream
        from trading.engine import TradingEngine

        self._signal_engine = SignalEngine(
            config_mgr=self.config_manager,
            binance_cli=self._binance_client,
            polymarket_cli=self._polymarket_client,
        )
        self._risk_manager = RiskManager(config_mgr=self.config_manager)
        self._order_manager = OrderManager(
            polymarket_cli=self._polymarket_client,
            bot_id=self.bot_id,
        )
        self._market_discovery = MarketDiscovery()
        self._market_stream = MarketDataStream()
        self._trading_engine = TradingEngine(
            config_mgr=self.config_manager,
            sig_engine=self._signal_engine,
            risk_mgr=self._risk_manager,
            order_mgr=self._order_manager,
            mkt_discovery=self._market_discovery,
            mkt_stream=self._market_stream,
            pm_client=self._polymarket_client,
            btc_client=self._binance_client,
            bot_id=self.bot_id,
        )

    def set_ws_broadcast(self, fn):
        self._ensure_components()
        self._trading_engine.set_ws_broadcast(fn)

    async def start(self):
        self._ensure_components()
        await self._trading_engine.start()

    async def stop(self):
        if self._trading_engine:
            await self._trading_engine.stop()

    @property
    def is_running(self) -> bool:
        return self._trading_engine.is_running if self._trading_engine else False

    @property
    def status(self) -> str:
        if self._trading_engine:
            return self._trading_engine.status.value
        return "stopped"

    def get_state(self) -> BotState:
        self._ensure_components()
        return self._trading_engine.get_state()

    def get_config(self) -> BotConfig:
        return self.config_manager.config

    def update_config(self, data: dict) -> BotConfig:
        updated = self.config_manager.update(data)
        db.update_bot(
            self.bot_id,
            config_json=json.dumps(updated.to_dict()),
            mode=updated.mode,
            updated_at=datetime.now(timezone.utc),
        )
        return updated
