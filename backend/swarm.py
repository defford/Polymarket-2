"""
SwarmManager — orchestrates multiple BotInstance objects.

Provides CRUD operations, lifecycle management (start/stop),
and aggregated statistics across all bots in the swarm.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import BotConfig, ConfigManager
from models import BotRecord
from bot_instance import BotInstance
from polymarket.client import PolymarketClient
from binance.client import binance_client
import database as db

logger = logging.getLogger(__name__)


class SwarmManager:
    """Manages all BotInstance objects."""

    def __init__(self):
        self._bots: dict[int, BotInstance] = {}  # bot_id -> BotInstance
        self._ws_broadcast_fn = None

    def set_ws_broadcast(self, fn):
        self._ws_broadcast_fn = fn
        # Wire existing bots
        for bot_id, instance in self._bots.items():
            instance.set_ws_broadcast(self._make_bot_broadcast(bot_id))

    async def initialize(self):
        """Load all bots from DB and create BotInstances."""
        bots = db.get_all_bots()

        if not bots:
            # First run — migrate existing bot_config.json as default "Bot 1"
            await self._create_default_bot()
            bots = db.get_all_bots()

        for bot_record in bots:
            config = BotConfig.from_dict(json.loads(bot_record.config_json))
            instance = self._create_instance(
                bot_record.id, bot_record.name, config, bot_record.description,
            )
            self._bots[bot_record.id] = instance
            logger.info(f"Loaded bot #{bot_record.id}: {bot_record.name}")

            # Auto-start if it was running/dry_run
            if bot_record.status in ("running", "dry_run"):
                logger.info(f"Resuming bot #{bot_record.id} in {bot_record.status} mode...")
                try:
                    # We use create_task to start them in parallel and not block init
                    asyncio.create_task(instance.start())
                except Exception as e:
                    logger.error(f"Failed to resume bot #{bot_record.id}: {e}")
                    db.update_bot(bot_record.id, status="error")

        logger.info(f"Swarm initialized with {len(self._bots)} bot(s)")

    async def _create_default_bot(self):
        """Create the default 'Bot 1' from existing config file."""
        try:
            existing_config = ConfigManager().config
        except Exception:
            existing_config = BotConfig()

        now = datetime.now(timezone.utc)
        record = BotRecord(
            name="Bot 1",
            description="Default trading bot",
            config_json=json.dumps(existing_config.to_dict()),
            mode=existing_config.mode,
            status="stopped",
            created_at=now,
            updated_at=now,
        )
        bot_id = db.create_bot(record)
        db.backfill_bot_ids(bot_id)
        logger.info(f"Created default bot (id={bot_id}) and backfilled existing data")

    def _create_instance(
        self, bot_id: int, name: str, config: BotConfig, description: str = "",
    ) -> BotInstance:
        # Each bot gets its own PolymarketClient to prevent
        # auth state clobbering when bots run in different modes.
        bot_pm_client = PolymarketClient()

        instance = BotInstance(
            bot_id=bot_id,
            name=name,
            config=config,
            description=description,
            polymarket_client=bot_pm_client,
            binance_client=binance_client,
        )
        if self._ws_broadcast_fn:
            instance.set_ws_broadcast(self._make_bot_broadcast(bot_id))
        return instance

    def _make_bot_broadcast(self, bot_id: int):
        """Create a broadcast function scoped to a specific bot."""
        async def broadcast(data: dict):
            if self._ws_broadcast_fn:
                await self._ws_broadcast_fn({
                    "type": "bot_state",
                    "bot_id": bot_id,
                    "state": data,
                })
        return broadcast

    # --- CRUD ---

    async def create_bot(
        self,
        name: str,
        description: str = "",
        config: Optional[BotConfig] = None,
        clone_from: Optional[int] = None,
    ) -> int:
        if config is None:
            if clone_from and clone_from in self._bots:
                config = BotConfig.from_dict(
                    self._bots[clone_from].get_config().to_dict()
                )
            else:
                config = BotConfig()

        now = datetime.now(timezone.utc)
        record = BotRecord(
            name=name,
            description=description,
            config_json=json.dumps(config.to_dict()),
            mode=config.mode,
            status="stopped",
            created_at=now,
            updated_at=now,
        )
        bot_id = db.create_bot(record)

        instance = self._create_instance(bot_id, name, config, description)
        self._bots[bot_id] = instance
        logger.info(f"Created bot #{bot_id}: {name}")
        return bot_id

    def get_bot(self, bot_id: int) -> Optional[BotInstance]:
        return self._bots.get(bot_id)

    def list_bots(self) -> list[dict]:
        result = []
        for bot_id, instance in self._bots.items():
            state = instance.get_state()
            result.append({
                "id": bot_id,
                "name": instance.name,
                "description": instance.description,
                "status": instance.status,
                "mode": instance.get_config().mode,
                "is_running": instance.is_running,
                "total_pnl": state.total_pnl,
                "daily_pnl": state.daily_pnl,
                "open_positions": len(state.open_positions),
                "total_trades": state.daily_stats.total_trades,
                "win_rate": state.daily_stats.win_rate,
                "consecutive_losses": state.consecutive_losses,
            })
        return result

    async def delete_bot(self, bot_id: int) -> bool:
        instance = self._bots.get(bot_id)
        if not instance:
            return False
        if instance.is_running:
            await instance.stop()
        del self._bots[bot_id]
        db.delete_bot(bot_id)
        logger.info(f"Deleted bot #{bot_id}")
        return True

    async def start_bot(self, bot_id: int):
        instance = self._bots.get(bot_id)
        if not instance:
            raise ValueError(f"Bot {bot_id} not found")
        try:
            await instance.start()
        except RuntimeError:
            db.update_bot(
                bot_id,
                status="error",
                updated_at=datetime.now(timezone.utc),
            )
            raise
        db.update_bot(
            bot_id,
            status=instance.status,
            updated_at=datetime.now(timezone.utc),
        )

    async def stop_bot(self, bot_id: int):
        instance = self._bots.get(bot_id)
        if not instance:
            raise ValueError(f"Bot {bot_id} not found")
        await instance.stop()
        db.update_bot(
            bot_id,
            status="stopped",
            updated_at=datetime.now(timezone.utc),
        )

    async def stop_all(self):
        for bot_id, instance in self._bots.items():
            if instance.is_running:
                try:
                    await instance.stop()
                except Exception as e:
                    logger.error(f"Error stopping bot #{bot_id}: {e}")

    def get_swarm_summary(self, time_scale: str = "all") -> dict:
        """Cumulative performance across all bots."""
        bot_ids = list(self._bots.keys())

        since = None
        now = datetime.now(timezone.utc)
        if time_scale == "hour":
            since = (now - timedelta(hours=1)).isoformat()
        elif time_scale == "day":
            since = (now - timedelta(days=1)).isoformat()

        stats = db.get_swarm_stats(bot_ids=bot_ids, since=since)

        active_bots = sum(1 for i in self._bots.values() if i.is_running)

        return {
            "total_bots": len(self._bots),
            "active_bots": active_bots,
            **stats,
        }

    def get_all_states(self) -> dict:
        """Return {bot_id_str: BotState_dict} for all bots."""
        all_states = {}
        for bot_id, instance in self._bots.items():
            try:
                all_states[str(bot_id)] = instance.get_state().model_dump(mode="json")
            except Exception as e:
                logger.debug(f"Error getting state for bot #{bot_id}: {e}")
        return all_states
