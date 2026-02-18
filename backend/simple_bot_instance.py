"""
SimpleBotInstance - A lightweight bot that executes basic limit order rules.

Simple Bots have no signal engine, risk manager, or complex configuration.
They simply place standing limit orders at specified prices and cycle
through buy→sell until stopped.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Optional, Callable

from models import (
    BotState, BotStatus, DailyStats, MarketInfo, Position, Side, Trade,
    OrderStatus, SimpleBotRule
)
from polymarket.client import PolymarketClient
from polymarket.markets import MarketDiscovery
import database as db

logger = logging.getLogger(__name__)

WINDOW_DURATION_SECONDS = 900
POLL_INTERVAL = 2.0


class SimpleBotInstance:
    """A simple bot that executes basic limit order rules."""

    def __init__(
        self,
        bot_id: int,
        name: str,
        rule: SimpleBotRule,
        description: str = "",
        mode: str = "dry_run",
        polymarket_client: Optional[PolymarketClient] = None,
    ):
        self.bot_id = bot_id
        self.name = name
        self.description = description
        self.rule = rule
        self.mode = mode
        self.is_dry_run = mode == "dry_run"

        self._polymarket_client = polymarket_client
        self._market_discovery = MarketDiscovery()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._current_position: Optional[Position] = None
        self._current_order_id: Optional[str] = None
        self._ws_broadcast: Optional[Callable] = None
        self._state_lock = asyncio.Lock()

        self._state = BotState(
            status=BotStatus.STOPPED,
            mode=mode,
        )

    def set_ws_broadcast(self, fn: Callable):
        self._ws_broadcast = fn

    @property
    def status(self) -> str:
        return self._state.status.value

    @property
    def is_running(self) -> bool:
        return self._running

    def get_state(self) -> BotState:
        return self._state

    async def start(self):
        if self._running:
            logger.warning(f"Simple bot #{self.bot_id} already running")
            return

        if self._polymarket_client is None:
            self._polymarket_client = PolymarketClient()

        if self.is_dry_run:
            self._polymarket_client.init_read_only()
        else:
            try:
                self._polymarket_client.init_authenticated()
            except Exception as e:
                logger.error(f"Failed to init authenticated client for bot #{self.bot_id}: {e}")
                self._state.status = BotStatus.ERROR
                raise RuntimeError(
                    f"Simple bot cannot start in live mode: {e}. "
                    f"Check POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS in .env."
                ) from e

        self._running = True
        self._state.status = BotStatus.RUNNING if not self.is_dry_run else BotStatus.DRY_RUN
        self._state.mode = self.mode
        logger.info(
            f"Simple bot #{self.bot_id} starting: {self.rule.buy_side.value} "
            f"buy@{self.rule.buy_price:.2f} sell@{self.rule.sell_price:.2f} "
            f"size=${self.rule.size_usd:.2f} mode={self.mode}"
        )

        self._task = asyncio.create_task(self._trading_loop())

    async def stop(self):
        if not self._running:
            return

        self._running = False

        if self._current_order_id and not self.is_dry_run:
            try:
                await self._polymarket_client.cancel_order(self._current_order_id)
                logger.info(f"Cancelled order {self._current_order_id}")
            except Exception as e:
                logger.warning(f"Failed to cancel order: {e}")

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._state.status = BotStatus.STOPPED
        logger.info(f"Simple bot #{self.bot_id} stopped")

    async def _trading_loop(self):
        """Main trading loop: buy -> sell -> repeat."""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self._running:
            try:
                await self._run_cycle()
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Simple bot #{self.bot_id} cycle error ({consecutive_errors}): {e}")
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Simple bot #{self.bot_id} stopping due to repeated errors")
                    self._state.status = BotStatus.ERROR
                    break
                await asyncio.sleep(5.0)

    async def _run_cycle(self):
        """Run one complete buy->sell cycle."""
        market = await self._get_market()
        if not market:
            logger.debug(f"No active market for bot #{self.bot_id}, waiting...")
            await asyncio.sleep(POLL_INTERVAL)
            return

        time_remaining = await self._get_time_remaining(market)
        if time_remaining and time_remaining < 60:
            logger.debug(f"Market closing soon for bot #{self.bot_id}, waiting for new window...")
            await asyncio.sleep(time_remaining + 5)
            return

        if self._current_position:
            await self._handle_sell(market)
        else:
            await self._handle_buy(market)

    async def _get_market(self) -> Optional[MarketInfo]:
        """Get the market to trade on."""
        if self.rule.market_condition_id:
            market_info = await self._market_discovery.scan_for_active_market()
            if market_info and market_info.condition_id == self.rule.market_condition_id:
                return market_info
            return None
        return await self._market_discovery.scan_for_active_market()

    async def _get_time_remaining(self, market: MarketInfo) -> Optional[float]:
        """Get time remaining until market closes."""
        if not market.end_time:
            return None
        now = datetime.now(timezone.utc)
        end = market.end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, (end - now).total_seconds())

    async def _handle_buy(self, market: MarketInfo):
        """Place and manage buy limit order."""
        token_id = market.up_token_id if self.rule.buy_side == Side.UP else market.down_token_id

        if not self.is_dry_run and not self._polymarket_client.is_authenticated:
            logger.error(f"Bot #{self.bot_id} not authenticated for live trading")
            await asyncio.sleep(10)
            return

        size_tokens = math.floor(self.rule.size_usd / self.rule.buy_price * 100) / 100

        if self.is_dry_run:
            await self._simulate_buy(market, token_id, size_tokens)
            return

        if self._current_order_id:
            existing_status = await self._check_order_status(self._current_order_id)
            if existing_status == "FILLED":
                logger.info(f"Buy order filled for bot #{self.bot_id}")
                await self._create_position_from_fill(market, token_id)
                return
            elif existing_status in ("CANCELED", "KILLED", "REJECTED"):
                self._current_order_id = None
            elif existing_status == "OPEN":
                time_remaining = await self._get_time_remaining(market)
                if time_remaining and time_remaining < 30:
                    await self._polymarket_client.cancel_order(self._current_order_id)
                    self._current_order_id = None
                    return
                await asyncio.sleep(POLL_INTERVAL)
                return
        else:
            try:
                resp = await self._polymarket_client.place_limit_order(
                    token_id=token_id,
                    price=self.rule.buy_price,
                    size=size_tokens,
                    side="BUY",
                    post_only=True,
                )
                if resp.get("success") or resp.get("orderID"):
                    self._current_order_id = resp.get("orderID") or resp.get("order_id")
                    logger.info(
                        f"Bot #{self.bot_id} placed buy order: "
                        f"{size_tokens:.2f} {self.rule.buy_side.value} @ {self.rule.buy_price:.2f} "
                        f"(order={self._current_order_id})"
                    )
                    trade = Trade(
                        timestamp=datetime.now(timezone.utc),
                        market_condition_id=market.condition_id,
                        side=self.rule.buy_side,
                        token_id=token_id,
                        price=self.rule.buy_price,
                        size=size_tokens,
                        cost=self.rule.size_usd,
                        status=OrderStatus.PENDING,
                        is_dry_run=False,
                        bot_id=self.bot_id,
                    )
                    trade.id = db.insert_trade(trade, bot_id=self.bot_id)
                    self._update_state_with_trade(trade)
                else:
                    error = resp.get("errorMsg", "Unknown error")
                    logger.warning(f"Bot #{self.bot_id} buy order rejected: {error}")
            except Exception as e:
                logger.error(f"Bot #{self.bot_id} error placing buy order: {e}")

        await asyncio.sleep(POLL_INTERVAL)

    async def _simulate_buy(self, market: MarketInfo, token_id: str, size_tokens: float):
        """Simulate a buy order in dry-run mode."""
        current_price = await self._polymarket_client.get_midpoint(token_id)

        if current_price <= self.rule.buy_price:
            logger.info(
                f"Bot #{self.bot_id} DRY RUN: Simulating buy fill @ {self.rule.buy_price:.2f} "
                f"(current price: {current_price:.2f})"
            )
            trade = Trade(
                timestamp=datetime.now(timezone.utc),
                market_condition_id=market.condition_id,
                side=self.rule.buy_side,
                token_id=token_id,
                price=self.rule.buy_price,
                size=size_tokens,
                cost=self.rule.size_usd,
                status=OrderStatus.FILLED,
                is_dry_run=True,
                order_id=f"dry_run_{int(datetime.now().timestamp() * 1000)}",
                bot_id=self.bot_id,
            )
            trade.id = db.insert_trade(trade, bot_id=self.bot_id)

            self._current_position = Position(
                market_condition_id=market.condition_id,
                side=self.rule.buy_side,
                token_id=token_id,
                entry_price=self.rule.buy_price,
                size=size_tokens,
                cost=self.rule.size_usd,
                current_price=current_price,
                peak_price=current_price,
                trough_price=current_price,
                entry_time=datetime.now(timezone.utc),
                is_dry_run=True,
            )

            async with self._state_lock:
                self._state.open_positions = [self._current_position]
                self._state.recent_trades = [trade] + self._state.recent_trades[:9]

            self._update_pnl()
            await self._broadcast_state()
        else:
            logger.debug(
                f"Bot #{self.bot_id} DRY RUN: Waiting for price to drop to {self.rule.buy_price:.2f} "
                f"(current: {current_price:.2f})"
            )
            await asyncio.sleep(POLL_INTERVAL)

    async def _handle_sell(self, market: MarketInfo):
        """Place and manage sell limit order."""
        if not self._current_position:
            return

        position = self._current_position

        if not self.is_dry_run and not self._polymarket_client.is_authenticated:
            logger.error(f"Bot #{self.bot_id} not authenticated for live trading")
            await asyncio.sleep(10)
            return

        if self.is_dry_run:
            await self._simulate_sell(market)
            return

        if self._current_order_id:
            existing_status = await self._check_order_status(self._current_order_id)
            if existing_status == "FILLED":
                logger.info(f"Sell order filled for bot #{self.bot_id}")
                await self._close_position_from_fill(market)
                return
            elif existing_status in ("CANCELED", "KILLED", "REJECTED"):
                self._current_order_id = None
            elif existing_status == "OPEN":
                time_remaining = await self._get_time_remaining(market)
                if time_remaining and time_remaining < 30:
                    await self._polymarket_client.cancel_order(self._current_order_id)
                    self._current_order_id = None
                    return
                await asyncio.sleep(POLL_INTERVAL)
                return
        else:
            try:
                resp = await self._polymarket_client.place_limit_order(
                    token_id=position.token_id,
                    price=self.rule.sell_price,
                    size=position.size,
                    side="SELL",
                    post_only=True,
                )
                if resp.get("success") or resp.get("orderID"):
                    self._current_order_id = resp.get("orderID") or resp.get("order_id")
                    logger.info(
                        f"Bot #{self.bot_id} placed sell order: "
                        f"{position.size:.2f} @ {self.rule.sell_price:.2f} "
                        f"(order={self._current_order_id})"
                    )
                else:
                    error = resp.get("errorMsg", "Unknown error")
                    logger.warning(f"Bot #{self.bot_id} sell order rejected: {error}")
            except Exception as e:
                logger.error(f"Bot #{self.bot_id} error placing sell order: {e}")

        await asyncio.sleep(POLL_INTERVAL)

    async def _simulate_sell(self, market: MarketInfo):
        """Simulate a sell order in dry-run mode."""
        if not self._current_position:
            return

        position = self._current_position
        current_price = await self._polymarket_client.get_midpoint(position.token_id)

        if current_price >= self.rule.sell_price:
            proceeds = self.rule.sell_price * position.size
            estimated_fee = proceeds * 0.02
            net_proceeds = proceeds - estimated_fee
            pnl = net_proceeds - position.cost

            logger.info(
                f"Bot #{self.bot_id} DRY RUN: Simulating sell fill @ {self.rule.sell_price:.2f} "
                f"(current: {current_price:.2f}) P&L=${pnl:+.2f}"
            )

            trade = Trade(
                timestamp=datetime.now(timezone.utc),
                market_condition_id=market.condition_id,
                side=position.side,
                token_id=position.token_id,
                price=self.rule.sell_price,
                size=position.size,
                cost=net_proceeds,
                status=OrderStatus.FILLED,
                pnl=pnl,
                fees=estimated_fee,
                is_dry_run=True,
                order_id=f"dry_run_{int(datetime.now().timestamp() * 1000)}",
                bot_id=self.bot_id,
            )
            trade.id = db.insert_trade(trade, bot_id=self.bot_id)

            db.update_trade(
                trade.id,
                pnl=pnl,
                fees=estimated_fee,
                status="filled",
            )

            async with self._state_lock:
                self._current_position = None
                self._state.open_positions = []
                self._state.recent_trades = [trade] + self._state.recent_trades[:9]

            self._update_pnl()
            await self._broadcast_state()
        else:
            logger.debug(
                f"Bot #{self.bot_id} DRY RUN: Waiting for price to rise to {self.rule.sell_price:.2f} "
                f"(current: {current_price:.2f})"
            )
            await asyncio.sleep(POLL_INTERVAL)

    async def _check_order_status(self, order_id: str) -> str:
        """Check the status of an order."""
        try:
            order = await self._polymarket_client.get_order(order_id)
            return order.get("status", "UNKNOWN") if order else "UNKNOWN"
        except Exception as e:
            logger.warning(f"Error checking order {order_id}: {e}")
            return "UNKNOWN"

    async def _create_position_from_fill(self, market: MarketInfo, token_id: str):
        """Create a position after buy order fills."""
        self._current_order_id = None

        trades = db.get_trades_for_market(market.condition_id)
        for trade in reversed(trades):
            if trade.bot_id == self.bot_id and trade.status == OrderStatus.PENDING:
                db.update_trade(trade.id, status="filled")
                self._current_position = Position(
                    market_condition_id=market.condition_id,
                    side=trade.side,
                    token_id=token_id,
                    entry_price=trade.price,
                    size=trade.size,
                    cost=trade.cost,
                    current_price=trade.price,
                    peak_price=trade.price,
                    trough_price=trade.price,
                    entry_time=datetime.now(timezone.utc),
                    is_dry_run=False,
                )
                async with self._state_lock:
                    self._state.open_positions = [self._current_position]
                    self._state.recent_trades = [trade] + self._state.recent_trades[:9]
                self._update_pnl()
                await self._broadcast_state()
                break

    async def _close_position_from_fill(self, market: MarketInfo):
        """Close position after sell order fills."""
        self._current_order_id = None

        if not self._current_position:
            return

        trades = db.get_trades_for_market(market.condition_id)
        for trade in reversed(trades):
            if trade.bot_id == self.bot_id and trade.status == OrderStatus.PENDING:
                sell_price = self.rule.sell_price
                proceeds = sell_price * self._current_position.size
                estimated_fee = proceeds * 0.02
                net_proceeds = proceeds - estimated_fee
                pnl = net_proceeds - self._current_position.cost

                db.update_trade(trade.id, pnl=pnl, fees=estimated_fee, status="filled")

                self._current_position = None
                async with self._state_lock:
                    self._state.open_positions = []
                    self._state.recent_trades = [trade] + self._state.recent_trades[:9]

                self._update_pnl()
                await self._broadcast_state()
                break

    def _update_state_with_trade(self, trade: Trade):
        """Update bot state with a new trade."""
        self._state.recent_trades = [trade] + self._state.recent_trades[:9]
        self._update_pnl()

    def _update_pnl(self):
        """Update P&L from database."""
        today_trades = db.get_today_trades(bot_id=self.bot_id)
        filled_trades = [t for t in today_trades if t.status == OrderStatus.FILLED]

        daily_pnl = sum(t.pnl or 0 for t in filled_trades)
        wins = len([t for t in filled_trades if (t.pnl or 0) > 0])
        losses = len([t for t in filled_trades if (t.pnl or 0) < 0])

        total_pnl = 0.0
        all_trades = db.get_trades(limit=1000, bot_id=self.bot_id)
        for t in all_trades:
            if t.status == OrderStatus.FILLED:
                total_pnl += t.pnl or 0

        self._state.daily_pnl = daily_pnl
        self._state.total_pnl = total_pnl
        self._state.daily_stats = DailyStats(
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            total_trades=len(filled_trades),
            winning_trades=wins,
            losing_trades=losses,
            total_pnl=daily_pnl,
            win_rate=wins / len(filled_trades) if filled_trades else 0.0,
        )

    async def _broadcast_state(self):
        """Broadcast state update via WebSocket."""
        if self._ws_broadcast:
            try:
                await self._ws_broadcast(self._state.model_dump(mode="json"))
            except Exception as e:
                logger.debug(f"Failed to broadcast state: {e}")

    async def resolve_position(self, resolution_price: float):
        """Resolve position when market closes."""
        if not self._current_position:
            return

        position = self._current_position
        payout = position.size * resolution_price
        pnl = payout - position.cost

        logger.info(
            f"Bot #{self.bot_id} position resolved: {position.side.value} "
            f"entry={position.entry_price:.3f} size={position.size:.2f} "
            f"payout=${payout:.2f} P&L=${pnl:+.2f}"
        )

        trades = db.get_trades_for_market(position.market_condition_id)
        for trade in reversed(trades):
            if trade.bot_id == self.bot_id and trade.status == OrderStatus.FILLED and trade.pnl is None:
                db.update_trade(trade.id, pnl=pnl, status="filled")
                break

        self._current_position = None
        async with self._state_lock:
            self._state.open_positions = []
        self._update_pnl()
        await self._broadcast_state()