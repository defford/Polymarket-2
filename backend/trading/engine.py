"""
Main Trading Engine.

The core loop that:
1. Discovers/rotates active 15-min BTC markets
2. Generates signals (Layer 1 + Layer 2)
3. Checks risk management
4. Places trades (or simulates in dry-run)
5. Tracks positions and resolves at market close
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from config import config_manager
from models import (
    BotStatus, BotState, CompositeSignal, MarketInfo, Side, Position, DailyStats,
    MarketStateSnapshot, Session,
)
from polymarket.client import polymarket_client
from polymarket.markets import market_discovery
from polymarket.orders import order_manager
from binance.client import binance_client
from signals.engine import signal_engine
from trading.risk import risk_manager
from trading.exits import evaluate_exit
import database as db

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    The main trading engine. Runs as an async loop.
    """

    def __init__(self):
        self._status = BotStatus.STOPPED
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_signal: Optional[CompositeSignal] = None
        self._previous_market_id: Optional[str] = None
        self._total_pnl = 0.0
        self._ws_broadcast_fn = None  # Set by main.py for WebSocket broadcasts
        self._current_session_id: Optional[int] = None

    @property
    def status(self) -> BotStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._running

    def set_ws_broadcast(self, fn):
        """Set the WebSocket broadcast function."""
        self._ws_broadcast_fn = fn

    async def start(self):
        """Start the trading engine."""
        if self._running:
            logger.warning("Trading engine already running")
            return

        config = config_manager.config

        # Initialize Polymarket client
        if config.mode == "live":
            try:
                polymarket_client.init_authenticated()
                self._status = BotStatus.RUNNING
            except Exception as e:
                logger.error(f"Failed to init authenticated client: {e}")
                logger.info("Falling back to dry-run mode")
                polymarket_client.init_read_only()
                self._status = BotStatus.DRY_RUN
        else:
            polymarket_client.init_read_only()
            self._status = BotStatus.DRY_RUN

        # Start new session
        new_session = Session(
            start_time=datetime.now(timezone.utc),
            start_balance=db.get_state("usdc_balance", 0.0), # Assuming this is tracked or we can fetch
            status=self._status.value,
        )
        try:
            # We don't have direct access to balance here easily without a client call or state
            # For now, start balance can be null or fetched if available
            pass
        except Exception:
            pass
            
        self._current_session_id = db.create_session(new_session)
        self._total_pnl = 0.0
        risk_manager.reset_session_stats()

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"🚀 Trading engine started in {self._status.value} mode")

    async def stop(self):
        """Stop the trading engine gracefully."""
        logger.info("Stopping trading engine...")
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        # Cancel any open orders
        order_manager.cancel_all()

        # Close session
        if self._current_session_id:
            db.update_session(
                self._current_session_id,
                end_time=datetime.now(timezone.utc),
                total_pnl=self._total_pnl,
                status="completed"
            )
            self._current_session_id = None

        self._status = BotStatus.STOPPED
        logger.info("Trading engine stopped")

    async def _run_loop(self):
        """Main trading loop."""
        config = config_manager.config.trading

        logger.info("Entering main trading loop")

        while self._running:
            try:
                loop_start = time.time()

                # Step 1: Discover/check active market
                market = await self._ensure_active_market()
                if not market:
                    logger.debug("No active market, waiting...")
                    await asyncio.sleep(config.market_discovery_interval_seconds)
                    continue

                # Step 2: Update market prices for dashboard
                self._update_market_prices(market)

                # Step 3: Check if too close to market close
                time_remaining = market_discovery.time_until_close()
                buffer_seconds = config_manager.config.risk.stop_trading_minutes_before_close * 60
                if market_discovery.should_stop_trading(buffer_seconds=buffer_seconds):
                    remaining_str = f"{time_remaining:.0f}s" if time_remaining is not None else "unknown"
                    logger.info(
                        f"⏳ Too close to market close (remaining: {remaining_str}, "
                        f"buffer: {buffer_seconds}s), waiting for next window"
                    )
                    await asyncio.sleep(5)
                    continue

                # Step 4: Compute signals
                composite_signal = signal_engine.compute_signal(market)
                self._last_signal = composite_signal

                # Step 5: Check risk and maybe trade
                await self._maybe_trade(market, composite_signal)

                # Step 5.5: Check exit conditions for open positions
                if order_manager.has_position(market.condition_id):
                    # Update prices first (also tracks peak for trailing stop)
                    order_manager.update_position_prices(market.condition_id)

                    position = order_manager._open_positions.get(market.condition_id)
                    if position:
                        exit_decision = evaluate_exit(position, composite_signal)
                        if exit_decision:
                            sell_state = self._capture_market_state(market, composite_signal)
                            is_dry = config_manager.config.mode != "live"
                            pnl = order_manager.sell_position(
                                market.condition_id,
                                reason=exit_decision["reason"],
                                is_dry_run=is_dry,
                                sell_state_snapshot=sell_state,
                            )
                            if pnl is not None:
                                risk_manager.record_trade_result(pnl, market.condition_id)
                                self._total_pnl += pnl
                                logger.info(
                                    f"💰 Early exit ({exit_decision['reason_category']}): "
                                    f"P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}"
                                )

                # Step 6: Update open position prices
                for pos in order_manager.open_positions:
                    order_manager.update_position_prices(pos.market_condition_id)

                # Step 7: Broadcast state via WebSocket
                await self._broadcast_state(market, composite_signal)

                # Step 8: Sleep until next iteration
                elapsed = time.time() - loop_start
                sleep_time = max(1, config.poll_interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Trading loop error: {e}", exc_info=True)
                self._status = BotStatus.ERROR
                await asyncio.sleep(10)  # Back off on error

    async def _ensure_active_market(self) -> Optional[MarketInfo]:
        """
        Ensure we have an active market. Handles rotation.
        """
        market = await market_discovery.scan_for_active_market()

        if market and market.condition_id != self._previous_market_id:
            # Market has changed — handle rotation
            if self._previous_market_id:
                await self._handle_market_close(self._previous_market_id)
                risk_manager.on_market_change(market.condition_id)

            self._previous_market_id = market.condition_id
            logger.info(f"📊 Active market: {market.question}")

        return market

    def _update_market_prices(self, market: MarketInfo):
        """
        Fetch and update the current Up/Down prices for the active market.
        Updates the market object in-place for the dashboard display.
        """
        try:
            market.up_price = polymarket_client.get_midpoint(market.up_token_id)
            market.down_price = polymarket_client.get_midpoint(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error updating market prices: {e}")

    def _capture_market_state(
        self,
        market: MarketInfo,
        signal: CompositeSignal,
    ) -> MarketStateSnapshot:
        """
        Capture complete market state snapshot at a point in time.
        Includes market info, signals, orderbooks, BTC data, risk state, and config.
        """
        timestamp = datetime.now(timezone.utc)
        
        # Capture orderbooks for both tokens
        orderbook_up = {}
        orderbook_down = {}
        try:
            if market.up_token_id:
                orderbook_up = polymarket_client.get_order_book(market.up_token_id)
        except Exception as e:
            logger.debug(f"Error capturing up token orderbook: {e}")
        
        try:
            if market.down_token_id:
                orderbook_down = polymarket_client.get_order_book(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error capturing down token orderbook: {e}")
        
        # Capture BTC price and candle summaries
        btc_price = None
        btc_candles_summary = {}
        try:
            btc_price = binance_client.get_current_price()
            # Get recent candle data summaries for each timeframe
            candles = binance_client.fetch_all_timeframes()
            for tf, df in candles.items():
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    btc_candles_summary[tf] = {
                        "open": float(latest["open"]),
                        "high": float(latest["high"]),
                        "low": float(latest["low"]),
                        "close": float(latest["close"]),
                        "volume": float(latest["volume"]),
                        "timestamp": latest.name.isoformat() if hasattr(latest.name, 'isoformat') else str(latest.name),
                    }
        except Exception as e:
            logger.debug(f"Error capturing BTC data: {e}")
        
        # Capture risk manager state
        risk_state = risk_manager.get_state()
        
        # Capture relevant config parameters
        config = config_manager.config
        config_snapshot = {
            "signal": {
                "pm_rsi_period": config.signal.pm_rsi_period,
                "pm_rsi_oversold": config.signal.pm_rsi_oversold,
                "pm_rsi_overbought": config.signal.pm_rsi_overbought,
                "pm_macd_fast": config.signal.pm_macd_fast,
                "pm_macd_slow": config.signal.pm_macd_slow,
                "pm_macd_signal": config.signal.pm_macd_signal,
                "pm_momentum_lookback": config.signal.pm_momentum_lookback,
                "layer1_weight": config.signal.layer1_weight,
                "layer2_weight": config.signal.layer2_weight,
                "buy_threshold": config.signal.buy_threshold,
            },
            "risk": {
                "max_position_size": config.risk.max_position_size,
                "max_trades_per_window": config.risk.max_trades_per_window,
                "max_daily_loss": config.risk.max_daily_loss,
                "min_signal_confidence": config.risk.min_signal_confidence,
                "max_consecutive_losses": config.risk.max_consecutive_losses,
                "cooldown_minutes": config.risk.cooldown_minutes,
                "stop_trading_minutes_before_close": config.risk.stop_trading_minutes_before_close,
            },
            "trading": {
                "order_type": config.trading.order_type,
                "price_offset": config.trading.price_offset,
                "use_fok_for_strong_signals": config.trading.use_fok_for_strong_signals,
                "strong_signal_threshold": config.trading.strong_signal_threshold,
            },
            "exit": {
                "enabled": config.exit.enabled,
                "trailing_stop_pct": config.exit.trailing_stop_pct,
                "hard_stop_pct": config.exit.hard_stop_pct,
                "signal_reversal_threshold": config.exit.signal_reversal_threshold,
                "tighten_at_seconds": config.exit.tighten_at_seconds,
                "tightened_trailing_pct": config.exit.tightened_trailing_pct,
                "final_seconds": config.exit.final_seconds,
                "final_trailing_pct": config.exit.final_trailing_pct,
                "min_hold_seconds": config.exit.min_hold_seconds,
                "pressure_scaling_enabled": config.exit.pressure_scaling_enabled,
            },
            "mode": config.mode,
        }
        
        # Capture market window information
        market_window_info = {}
        try:
            time_remaining = market_discovery.time_until_close()
            market_window_info = {
                "time_until_close_seconds": time_remaining,
                "should_stop_trading": market_discovery.should_stop_trading(),
                "current_window_timestamp": market_discovery.get_current_window_timestamp(),
                "next_window_timestamp": market_discovery.get_next_window_timestamp(),
            }
        except Exception as e:
            logger.debug(f"Error capturing window info: {e}")
        
        # Prepare OrderBook data as simple dictionaries for the snapshot
        # The raw py-clob-client returns OrderBookSummary objects which Pydantic can't validate as dicts
        def _to_dict(obj):
            if hasattr(obj, "to_dict"):
                return obj.to_dict()
            if hasattr(obj, "__dict__"):
                return obj.__dict__
            return obj

        orderbook_up_dict = _to_dict(orderbook_up) if orderbook_up else {}
        orderbook_down_dict = _to_dict(orderbook_down) if orderbook_down else {}

        return MarketStateSnapshot(
            timestamp=timestamp,
            market=market,
            signal=signal,
            orderbook_up=orderbook_up_dict,
            orderbook_down=orderbook_down_dict,
            btc_price=btc_price,
            btc_candles_summary=btc_candles_summary,
            risk_state=risk_state,
            config_snapshot=config_snapshot,
            market_window_info=market_window_info,
        )

    async def _handle_market_close(self, old_condition_id: str):
        """
        Handle the close of a 15-min market.
        Resolve any open position.
        """
        if not order_manager.has_position(old_condition_id):
            return

        position = [p for p in order_manager.open_positions
                     if p.market_condition_id == old_condition_id]
        if not position:
            return

        pos = position[0]

        # Get current market info for state capture
        # Try to get the market that's closing (may not be current anymore)
        market = market_discovery.current_market
        if not market or market.condition_id != old_condition_id:
            # Market has rotated, try to get market info from trades or create minimal
            trades = db.get_trades_for_market(old_condition_id)
            if trades:
                # Get token IDs from the trade
                trade = trades[0]
                from models import MarketInfo
                if pos.side == Side.UP:
                    # We hold UP token, need to find DOWN token
                    # For now, create minimal market with what we know
                    market = MarketInfo(
                        condition_id=old_condition_id,
                        question="Market Closing",
                        up_token_id=pos.token_id,
                        down_token_id="",  # Will be empty, but orderbook capture will handle it
                    )
                else:
                    market = MarketInfo(
                        condition_id=old_condition_id,
                        question="Market Closing",
                        up_token_id="",  # Will be empty, but orderbook capture will handle it
                        down_token_id=pos.token_id,
                    )
            else:
                # Fallback: create minimal market
                from models import MarketInfo
                market = MarketInfo(
                    condition_id=old_condition_id,
                    question="Market Closing",
                    up_token_id=pos.token_id if pos.side == Side.UP else "",
                    down_token_id=pos.token_id if pos.side == Side.DOWN else "",
                )

        # Determine resolution: did BTC go up or down?
        # The simplest approach: check BTC price change over the window
        # In practice, Polymarket uses a specific oracle/price source
        btc_price = binance_client.get_current_price()

        # For dry-run, we simulate resolution based on final token price
        # In live mode, the market resolves automatically (token → $1 or $0)
        try:
            final_price = polymarket_client.get_midpoint(pos.token_id)
        except Exception:
            final_price = 0.5  # Unknown — assume neutral

        # If market has resolved: token price should be near 0 or 1
        if final_price > 0.8:
            resolution = 1.0  # Won
        elif final_price < 0.2:
            resolution = 0.0  # Lost
        else:
            # Market may not have resolved yet, estimate based on direction
            # This is a simplification — in production you'd wait for settlement
            resolution = final_price

        # Capture sell state snapshot before resolving
        # Use a minimal signal since we're at market close
        minimal_signal = CompositeSignal(
            composite_score=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        sell_state_snapshot = self._capture_market_state(market, minimal_signal)

        pnl = order_manager.resolve_position(
            old_condition_id,
            resolution,
            sell_state_snapshot=sell_state_snapshot,
        )
        if pnl is not None:
            risk_manager.record_trade_result(pnl, old_condition_id)
            self._total_pnl += pnl
            logger.info(f"💰 Position resolved: P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}")

    async def _maybe_trade(self, market: MarketInfo, signal: CompositeSignal):
        """Check risk rules and place trade if appropriate."""
        config = config_manager.config

        # Don't trade if we already have a position in this market
        if order_manager.has_position(market.condition_id):
            return

        # Check risk management
        allowed, reason = risk_manager.can_trade(signal, market.condition_id)
        if not allowed:
            logger.debug(f"Trade blocked: {reason}")
            return

        # ─── NEW: Price Ceiling Check ───
        # Prevent buying the top. Don't enter if price is > 80c.
        max_entry = config.risk.max_entry_price
        current_price = 0.5
        if signal.recommended_side == Side.UP:
            current_price = market.up_price if market.up_price else 0.5
        elif signal.recommended_side == Side.DOWN:
            current_price = market.down_price if market.down_price else 0.5

        if current_price > max_entry:
            logger.info(f"🚫 Trade Skipped: Price {current_price:.2f} exceeds max entry {max_entry:.2f}")
            return

        # Determine position size
        position_size = risk_manager.get_position_size()

        # Determine order type
        order_type = config.trading.order_type
        if (
            config.trading.use_fok_for_strong_signals
            and abs(signal.composite_score) >= config.trading.strong_signal_threshold
        ):
            order_type = "market"

        # Capture market state snapshot before placing trade
        buy_state_snapshot = self._capture_market_state(market, signal)

        # Place the trade
        is_dry_run = config.mode != "live"
        trade = order_manager.place_order(
            market=market,
            side=signal.recommended_side,
            size_usd=position_size,
            order_type=order_type,
            price_offset=config.trading.price_offset,
            is_dry_run=is_dry_run,
            signal_score=signal.composite_score,
            buy_state_snapshot=buy_state_snapshot,
            session_id=self._current_session_id,
        )

        if trade:
            logger.info(
                f"{'🧪' if is_dry_run else '✅'} "
                f"{'DRY RUN' if is_dry_run else 'LIVE'}: "
                f"{signal.recommended_side.value.upper()} "
                f"${position_size:.2f} @ {trade.price:.3f} "
                f"(signal={signal.composite_score:+.3f})"
            )

    async def _broadcast_state(self, market: MarketInfo, signal: CompositeSignal):
        """Broadcast current state to WebSocket clients."""
        if not self._ws_broadcast_fn:
            return

        try:
            state = self.get_state(market, signal)
            await self._ws_broadcast_fn(state.model_dump(mode="json"))
        except Exception as e:
            logger.debug(f"Broadcast error: {e}")

    def get_state(
        self,
        market: Optional[MarketInfo] = None,
        signal: Optional[CompositeSignal] = None,
    ) -> BotState:
        """Get the full bot state for the dashboard."""
        if market is None:
            market = market_discovery.current_market
        if signal is None:
            signal = self._last_signal

        if self._current_session_id:
            daily_stats = db.get_session_stats(self._current_session_id)
            recent_trades = db.get_trades_for_session(self._current_session_id)
            # We take top 20 for the dashboard list
            recent_trades = recent_trades[:20]
        else:
            # Fallback to daily stats if no active session
            daily_stats = db.get_daily_stats()
            recent_trades = db.get_trades(limit=20)

        # Determine effective status
        status = self._status
        if risk_manager.is_in_cooldown:
            status = BotStatus.COOLDOWN

        return BotState(
            status=status,
            mode=config_manager.config.mode,
            current_market=market,
            current_signal=signal,
            open_positions=order_manager.open_positions,
            recent_trades=recent_trades,
            daily_stats=daily_stats,
            consecutive_losses=risk_manager.consecutive_losses,
            daily_pnl=risk_manager.daily_pnl,
            total_pnl=self._total_pnl,
            last_updated=datetime.now(timezone.utc),
        )


# Global singleton
trading_engine = TradingEngine()
