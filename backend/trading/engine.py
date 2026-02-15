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
    BotStatus, BotState, CompositeSignal, MarketInfo, Side,
    MarketStateSnapshot, Session, OrderStatus,
)
from polymarket.client import polymarket_client
from polymarket.markets import market_discovery
from polymarket.orders import order_manager
from binance.client import binance_client
from signals.engine import signal_engine
from trading.risk import risk_manager
from trading.exits import evaluate_exit
from polymarket.stream import market_stream
import database as db

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    The main trading engine. Runs as an async loop.
    """

    def __init__(
        self,
        config_mgr=None,
        sig_engine=None,
        risk_mgr=None,
        order_mgr=None,
        mkt_discovery=None,
        mkt_stream=None,
        pm_client=None,
        btc_client=None,
        bot_id=None,
        bayesian_mgr=None,
    ):
        # Dependency injection (None = use global singletons for backward compat)
        self._config_mgr = config_mgr
        self._sig_engine = sig_engine
        self._risk_mgr = risk_mgr
        self._order_mgr = order_mgr
        self._mkt_discovery = mkt_discovery
        self._mkt_stream = mkt_stream
        self._pm_client = pm_client
        self._btc_client = btc_client
        self._bot_id = bot_id
        self._bayesian_mgr = bayesian_mgr

        self._status = BotStatus.STOPPED
        self._running = False
        self._strategy_task: Optional[asyncio.Task] = None
        self._risk_task: Optional[asyncio.Task] = None
        self._last_signal: Optional[CompositeSignal] = None
        self._previous_market_id: Optional[str] = None
        self._total_pnl = 0.0
        self._ws_broadcast_fn = None  # Set by main.py for WebSocket broadcasts
        self._current_session_id: Optional[int] = None
        self._position_lock = asyncio.Lock()  # Protects _open_positions from concurrent access

    # Accessor helpers — fall back to module-level globals if no DI
    @property
    def _cfg(self):
        return self._config_mgr if self._config_mgr is not None else config_manager

    @property
    def _signals(self):
        return self._sig_engine if self._sig_engine is not None else signal_engine

    @property
    def _risk(self):
        return self._risk_mgr if self._risk_mgr is not None else risk_manager

    @property
    def _orders(self):
        return self._order_mgr if self._order_mgr is not None else order_manager

    @property
    def _discovery(self):
        return self._mkt_discovery if self._mkt_discovery is not None else market_discovery

    @property
    def _stream(self):
        return self._mkt_stream if self._mkt_stream is not None else market_stream

    @property
    def _polymarket(self):
        return self._pm_client if self._pm_client is not None else polymarket_client

    @property
    def _binance(self):
        return self._btc_client if self._btc_client is not None else binance_client

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

        config = self._cfg.config

        # Initialize Polymarket client
        if config.mode == "live":
            try:
                self._polymarket.init_authenticated()
                self._status = BotStatus.RUNNING
            except Exception as e:
                logger.error(f"Failed to init authenticated client: {e}")
                self._status = BotStatus.ERROR
                raise RuntimeError(
                    f"Bot cannot start in live mode: {e}. "
                    f"Check POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS in .env."
                ) from e
        else:
            self._polymarket.init_read_only()
            self._status = BotStatus.DRY_RUN

        # Start new session
        new_session = Session(
            start_time=datetime.now(timezone.utc),
            start_balance=db.get_state("usdc_balance", 0.0),
            status=self._status.value,
        )

        self._current_session_id = db.create_session(new_session, bot_id=self._bot_id)
        self._total_pnl = 0.0
        self._risk.reset_session_stats()

        # Start WebSocket stream for real-time prices
        await self._stream.start()

        self._running = True
        self._strategy_task = asyncio.create_task(self._slow_strategy_loop())
        self._risk_task = asyncio.create_task(self._fast_risk_loop())
        logger.info(f"🚀 Trading engine started in {self._status.value} mode")

    async def stop(self):
        """Stop the trading engine gracefully."""
        logger.info("Stopping trading engine...")
        self._running = False

        # Stop WebSocket price stream
        await self._stream.stop()

        # Cancel both loop tasks
        for task in [self._strategy_task, self._risk_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Cancel any open orders
        self._orders.cancel_all()

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

    # ------------------------------------------------------------------
    # Slow strategy loop  (runs every poll_interval_seconds ~10s)
    # Handles: market discovery, signal computation, trade entries,
    #          full exit evaluation (BTC pressure + signal reversal),
    #          and dashboard broadcast.
    # ------------------------------------------------------------------

    async def _slow_strategy_loop(self):
        """Strategy & signal loop — runs every poll_interval_seconds."""
        config = self._cfg.config.trading

        logger.info("Entering strategy loop")

        while self._running:
            try:
                loop_start = time.time()

                # Step 1: Discover/check active market
                market = await self._ensure_active_market()
                if not market:
                    logger.debug("No active market, waiting...")
                    await asyncio.sleep(config.market_discovery_interval_seconds)
                    continue

                # Step 2: Update market prices via HTTP (accurate for signals)
                self._update_market_prices(market)

                # Step 3: Check if too close to market close
                time_remaining = self._discovery.time_until_close()
                buffer_seconds = self._cfg.config.risk.stop_trading_minutes_before_close * 60
                if self._discovery.should_stop_trading(buffer_seconds=buffer_seconds):
                    remaining_str = f"{time_remaining:.0f}s" if time_remaining is not None else "unknown"
                    logger.info(
                        f"⏳ Too close to market close (remaining: {remaining_str}, "
                        f"buffer: {buffer_seconds}s), waiting for next window"
                    )
                    await asyncio.sleep(5)
                    continue

                # Step 4: Compute signals
                composite_signal = self._signals.compute_signal(market)
                self._last_signal = composite_signal

                # Step 4.5: Bayesian posterior calculation
                if self._cfg.config.bayesian.enabled and self._bayesian_mgr:
                    bayes_result = self._bayesian_mgr.compute_posterior(
                        composite_signal.l1_evidence,
                        composite_signal.l2_evidence,
                    )
                    composite_signal.bayesian_posterior = bayes_result['posterior']
                    composite_signal.bayesian_confidence_gate = bayes_result['confidence_gate']
                    composite_signal.bayesian_fallback = bayes_result['fallback']
                    
                    if not bayes_result['confidence_gate']:
                        logger.info(
                            f"🚫 Bayesian gate BLOCKED: posterior={bayes_result['posterior']:.2f} "
                            f"(threshold=0.4) l1={composite_signal.l1_evidence} l2={composite_signal.l2_evidence}"
                        )
                    elif not bayes_result['fallback']:
                        logger.info(
                            f"📊 Bayesian POSTERIOR: {bayes_result['posterior']:.2f} "
                            f"(prior={bayes_result['prior']:.2f}) "
                            f"l1={composite_signal.l1_evidence} l2={composite_signal.l2_evidence}"
                        )

                # Step 5: Check risk and maybe trade
                await self._maybe_trade(market, composite_signal)

                # Step 5.5: Update position prices via HTTP when WS is stale
                if self._orders.has_position(market.condition_id):
                    pos = self._orders._open_positions.get(market.condition_id)
                    if pos and not self._stream.is_price_fresh(pos.token_id):
                        self._orders.update_position_prices(market.condition_id)

                # Step 6: Full exit evaluation (signal reversal + BTC pressure)
                # The fast loop handles price-based stops in real-time; this
                # catches BTC-pressure-adjusted trailing stops and signal flips.
                if self._orders.has_position(market.condition_id):
                    position = self._orders._open_positions.get(market.condition_id)
                    if position:
                        exit_decision = evaluate_exit(
                            position, composite_signal,
                            config_mgr=self._cfg, mkt_discovery=self._discovery,
                            btc_client=self._binance,
                        )
                        if exit_decision:
                            await self._execute_exit(
                                market.condition_id,
                                exit_decision["reason"],
                                exit_decision["reason_category"],
                                effective_trailing_pct=exit_decision.get("effective_trailing_pct"),
                                time_zone=exit_decision.get("time_zone"),
                            )

                # Step 7: Broadcast state via WebSocket
                await self._broadcast_state(market, composite_signal)

                # Step 8: Sleep until next iteration
                elapsed = time.time() - loop_start
                sleep_time = max(1, config.poll_interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Strategy loop error: {e}", exc_info=True)
                self._status = BotStatus.ERROR
                await asyncio.sleep(10)  # Back off on error

    # ------------------------------------------------------------------
    # Fast risk loop  (runs every ~0.25s)
    # Reads prices from the WebSocket cache and checks stop-loss
    # conditions.  This is the sub-second safety net that prevents
    # the slippage we saw with 10-second polling.
    # ------------------------------------------------------------------

    async def _fast_risk_loop(self):
        """High-frequency exit check — reads from WS price cache."""
        logger.info("Entering fast risk loop")

        while self._running:
            try:
                exit_config = self._cfg.config.exit
                if not exit_config.enabled:
                    await asyncio.sleep(1.0)
                    continue

                # Update dashboard market prices from WS cache
                market = self._discovery.current_market
                if market:
                    up_mid = self._stream.prices.get_midpoint(market.up_token_id)
                    down_mid = self._stream.prices.get_midpoint(market.down_token_id)
                    if up_mid is not None:
                        market.up_price = up_mid
                    if down_mid is not None:
                        market.down_price = down_mid

                # Iterate over all open positions
                exited = False
                for condition_id, position in list(self._orders._open_positions.items()):
                    ws_price = self._stream.prices.get_midpoint(position.token_id)
                    if ws_price is None or not self._stream.is_price_fresh(position.token_id):
                        # WS stale — fall back to HTTP for safety
                        try:
                            ws_price = self._polymarket.get_midpoint(position.token_id)
                        except Exception:
                            continue  # Can't get price at all, skip this check
                    if ws_price is None:
                        continue

                    # Update position with real-time WS price
                    position.current_price = ws_price
                    position.unrealized_pnl = (ws_price - position.entry_price) * position.size
                    if ws_price > position.peak_price:
                        position.peak_price = ws_price
                    if ws_price < position.trough_price or position.trough_price == 0:
                        position.trough_price = ws_price

                    # Check minimum hold time
                    if position.entry_time:
                        held = (datetime.now(timezone.utc) - position.entry_time).total_seconds()
                        if held < exit_config.min_hold_seconds:
                            continue

                    # Determine time-based trailing stop
                    time_remaining = self._discovery.time_until_close()
                    base_trailing = exit_config.trailing_stop_pct
                    time_zone = "normal"
                    if time_remaining is not None:
                        if time_remaining <= exit_config.final_seconds:
                            base_trailing = exit_config.final_trailing_pct
                            time_zone = "FINAL"
                        elif time_remaining <= exit_config.tighten_at_seconds:
                            base_trailing = exit_config.tightened_trailing_pct
                            time_zone = "TIGHT"

                    # --- Scaling Take Profit: tighten trailing stop based on unrealized gain ---
                    if exit_config.scaling_tp_enabled and position.entry_price > 0 and position.current_price > position.entry_price:
                        gain_pct = (position.current_price - position.entry_price) / position.entry_price
                        stop_reduction = exit_config.scaling_tp_pct * gain_pct
                        base_trailing = base_trailing * (1.0 - stop_reduction)
                        base_trailing = max(base_trailing, exit_config.scaling_tp_min_trail)

                    # --- Trailing stop (no BTC pressure — slow loop handles that) ---
                    if position.peak_price > 0 and position.current_price > 0:
                        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price
                        if drop_from_peak >= base_trailing:
                            reason = (
                                f"trailing_stop: price {position.current_price:.3f} dropped "
                                f"{drop_from_peak:.1%} from peak {position.peak_price:.3f} | "
                                f"effective={base_trailing:.1%} [{time_zone}] (WS fast-check)"
                            )
                            logger.info(f"🛑 FAST EXIT -- {reason}")
                            await self._execute_exit(
                                condition_id, reason, "trailing_stop",
                                effective_trailing_pct=base_trailing,
                                time_zone=time_zone,
                            )
                            exited = True
                            break

                    # --- Hard stop (absolute safety net) ---
                    if position.entry_price > 0 and position.current_price > 0:
                        drop_from_entry = (position.entry_price - position.current_price) / position.entry_price
                        if drop_from_entry >= exit_config.hard_stop_pct:
                            reason = (
                                f"hard_stop: price {position.current_price:.3f} dropped "
                                f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                                f"(hard limit: {exit_config.hard_stop_pct:.0%}) (WS fast-check)"
                            )
                            logger.info(f"🛑 FAST EXIT -- {reason}")
                            await self._execute_exit(condition_id, reason, "hard_stop")
                            exited = True
                            break

                    # --- Hard Take Profit (absolute profit ceiling) ---
                    if exit_config.hard_tp_enabled and position.entry_price > 0 and position.current_price > 0:
                        gain_from_entry = (position.current_price - position.entry_price) / position.entry_price
                        if gain_from_entry >= exit_config.hard_tp_pct:
                            reason = (
                                f"hard_take_profit: price {position.current_price:.3f} rose "
                                f"{gain_from_entry:.1%} from entry {position.entry_price:.3f} "
                                f"(hard TP limit: {exit_config.hard_tp_pct:.0%}) (WS fast-check)"
                            )
                            logger.info(f"🎯 FAST EXIT -- {reason}")
                            await self._execute_exit(condition_id, reason, "hard_take_profit")
                            exited = True
                            break

                await asyncio.sleep(1.0 if exited else 0.25)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fast risk loop error: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # Shared exit execution helper
    # ------------------------------------------------------------------

    async def _execute_exit(
        self,
        condition_id: str,
        reason: str,
        reason_category: str,
        effective_trailing_pct: Optional[float] = None,
        time_zone: Optional[str] = None,
    ):
        """
        Execute a position exit.  Shared by both the fast and slow loops.

        Captures market state, places the sell, records the P&L, and logs.
        Protected by _position_lock to prevent concurrent exit on the same position.
        """
        async with self._position_lock:
            # Check position still exists (may have been closed by other loop)
            if not self._orders.has_position(condition_id):
                logger.debug(f"Position {condition_id[:16]} already closed, skipping exit")
                return

            market = self._discovery.current_market
            signal = self._last_signal or CompositeSignal(
                composite_score=0.0,
                timestamp=datetime.now(timezone.utc),
            )

            sell_state = None
            if market:
                try:
                    sell_state = self._capture_market_state(market, signal)
                except Exception as e:
                    logger.debug(f"Error capturing sell state: {e}")

            is_dry = self._cfg.config.mode != "live"
            pnl = await self._orders.sell_position(
                condition_id,
                reason=reason,
                is_dry_run=is_dry,
                sell_state_snapshot=sell_state,
                effective_trailing_pct=effective_trailing_pct,
                time_zone=time_zone,
            )
            if pnl is not None:
                self._risk.record_trade_result(pnl, condition_id)
                self._total_pnl += pnl
                logger.info(
                    f"💰 Early exit ({reason_category}): "
                    f"P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}"
                )
                
                # Record Bayesian outcome
                if self._cfg.config.bayesian.enabled and self._bayesian_mgr and self._last_signal:
                    won = pnl > 0
                    self._bayesian_mgr.record_outcome(
                        self._last_signal.l1_evidence,
                        self._last_signal.l2_evidence,
                        won,
                    )

    async def _ensure_active_market(self) -> Optional[MarketInfo]:
        """
        Ensure we have an active market. Handles rotation and WS subscriptions.
        """
        market = await self._discovery.scan_for_active_market()

        if market and market.condition_id != self._previous_market_id:
            # Market has changed — handle rotation
            if self._previous_market_id:
                await self._handle_market_close(self._previous_market_id)
                self._risk.on_market_change(market.condition_id)

            self._previous_market_id = market.condition_id
            logger.info(f"📊 Active market: {market.question}")

            # Subscribe to new market tokens via WebSocket for real-time prices
            tokens = [t for t in [market.up_token_id, market.down_token_id] if t]
            if tokens:
                self._stream.subscribe(tokens)

        return market

    def _update_market_prices(self, market: MarketInfo):
        """
        Fetch and update the current Up/Down prices for the active market.
        Updates the market object in-place for the dashboard display.
        """
        try:
            market.up_price = self._polymarket.get_midpoint(market.up_token_id)
            market.down_price = self._polymarket.get_midpoint(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error updating market prices: {e}")

    @staticmethod
    def compute_orderbook_imbalance(orderbook: dict) -> dict:
        """
        Compute bid/ask volume imbalance and spread from an order book.
        
        Enhanced to include top-10 depth for survival analysis.
        """
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        # Top 5 levels (existing)
        bid_vol_5 = sum(float(b.get("size", 0)) for b in bids[:5])
        ask_vol_5 = sum(float(a.get("size", 0)) for a in asks[:5])
        total_5 = bid_vol_5 + ask_vol_5

        # Top 10 levels (new)
        bid_vol_10 = sum(float(b.get("size", 0)) for b in bids[:10])
        ask_vol_10 = sum(float(a.get("size", 0)) for a in asks[:10])
        total_10 = bid_vol_10 + ask_vol_10

        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        
        # Spread in basis points
        spread = (best_ask - best_bid) if best_bid and best_ask else 0
        spread_bps = (spread / best_bid * 10000) if best_bid > 0 else 0
        
        # Depth ratio: bid/ask (values > 1 = more bid liquidity)
        depth_ratio = (bid_vol_10 / ask_vol_10) if ask_vol_10 > 0 else 0

        return {
            "bid_volume_top5": round(bid_vol_5, 2),
            "ask_volume_top5": round(ask_vol_5, 2),
            "bid_volume_top10": round(bid_vol_10, 2),
            "ask_volume_top10": round(ask_vol_10, 2),
            "imbalance": round((bid_vol_5 - ask_vol_5) / total_5, 4) if total_5 > 0 else 0,
            "imbalance_top10": round((bid_vol_10 - ask_vol_10) / total_10, 4) if total_10 > 0 else 0,
            "spread": round(spread, 4),
            "spread_bps": round(spread_bps, 2),
            "depth_ratio": round(depth_ratio, 4),
            "liquidity_score": round(total_10, 2),
            "best_bid": best_bid,
            "best_ask": best_ask,
        }

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
                orderbook_up = self._polymarket.get_order_book(market.up_token_id)
        except Exception as e:
            logger.debug(f"Error capturing up token orderbook: {e}")
        
        try:
            if market.down_token_id:
                orderbook_down = self._polymarket.get_order_book(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error capturing down token orderbook: {e}")
        
        # Capture BTC price and candle summaries
        btc_price = None
        btc_candles_summary = {}
        try:
            btc_price = self._binance.get_current_price()
            # Get recent candle data summaries for each timeframe
            candles = self._binance.fetch_all_timeframes()
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
        risk_state = self._risk.get_state()
        
        # Capture relevant config parameters
        config = self._cfg.config
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
                "vwap_enabled": config.signal.vwap_enabled,
                "vwap_weight": config.signal.vwap_weight,
                "vroc_enabled": config.signal.vroc_enabled,
                "vroc_threshold": config.signal.vroc_threshold,
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
            time_remaining = self._discovery.time_until_close()
            market_window_info = {
                "time_until_close_seconds": time_remaining,
                "should_stop_trading": self._discovery.should_stop_trading(),
                "current_window_timestamp": self._discovery.get_current_window_timestamp(),
                "next_window_timestamp": self._discovery.get_next_window_timestamp(),
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
        if not self._orders.has_position(old_condition_id):
            return

        position = [p for p in self._orders.open_positions
                     if p.market_condition_id == old_condition_id]
        if not position:
            return

        pos = position[0]

        # Get current market info for state capture
        # Try to get the market that's closing (may not be current anymore)
        market = self._discovery.current_market
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
        # Query Polymarket API for the official outcome
        resolution = 0.5  # Default to neutral/unknown

        try:
            market_data = self._polymarket.get_market(old_condition_id)
            
            # Check if market is resolved/closed
            if market_data and (market_data.get("closed") or market_data.get("resolved")):
                # Check tokens for explicit winner flag
                tokens = market_data.get("tokens", [])
                winner_found = False
                
                for t in tokens:
                    if t.get("winner") is True:
                        winner_found = True
                        if t.get("token_id") == pos.token_id:
                            resolution = 1.0  # We won
                        else:
                            # Verify if this matches the other side (implies we lost)
                            resolution = 0.0  # We lost
                        break
                
                if not winner_found:
                    logger.warning(f"Market {old_condition_id} closed but no winner flag found in tokens")
                    # Fallback: check prices if avail, or keep 0.5
            
            # If still 0.5, try the price method as backup (but carefully)
            if resolution == 0.5:
                final_price = self._polymarket.get_midpoint(pos.token_id)
                if final_price > 0.9:
                    resolution = 1.0
                elif final_price < 0.1:
                    resolution = 0.0
                
        except Exception as e:
            logger.error(f"Error determining resolution for {old_condition_id}: {e}")
            resolution = 0.5

        # Capture sell state snapshot before resolving
        # Use a minimal signal since we're at market close
        minimal_signal = CompositeSignal(
            composite_score=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        sell_state_snapshot = self._capture_market_state(market, minimal_signal)

        pnl = self._orders.resolve_position(
            old_condition_id,
            resolution,
            sell_state_snapshot=sell_state_snapshot,
        )
        if pnl is not None:
            self._risk.record_trade_result(pnl, old_condition_id)
            self._total_pnl += pnl
            logger.info(f"💰 Position resolved: P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}")
            
            # Record Bayesian outcome
            if self._cfg.config.bayesian.enabled and self._bayesian_mgr and self._last_signal:
                won = pnl > 0
                self._bayesian_mgr.record_outcome(
                    self._last_signal.l1_evidence,
                    self._last_signal.l2_evidence,
                    won,
                )

    async def _maybe_trade(self, market: MarketInfo, signal: CompositeSignal):
        """Check risk rules and place trade if appropriate."""
        config = self._cfg.config

        # Check risk management (outside lock — read-only checks)
        allowed, reason = self._risk.can_trade(signal, market.condition_id)
        if not allowed:
            logger.debug(f"Trade blocked: {reason}")
            return

        # Bayesian confidence gate check
        if config.bayesian.enabled and not signal.bayesian_confidence_gate:
            logger.info(
                f"🚫 Trade blocked by Bayesian confidence gate: "
                f"posterior={signal.bayesian_posterior:.2f} < threshold=0.4"
            )
            return

        # Price Ceiling Check — prevent buying the top
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
        position_size = self._risk.get_position_size()
        if position_size <= 0:
            logger.debug("Position size is 0, can't trade")
            return

        # Determine order type
        order_type = config.trading.order_type
        if (
            config.trading.use_fok_for_strong_signals
            and abs(signal.composite_score) >= config.trading.strong_signal_threshold
        ):
            order_type = "market"

        # Capture market state snapshot before placing trade
        buy_state_snapshot = self._capture_market_state(market, signal)

        # Lock to prevent race with exit loop when checking/creating position
        is_dry_run = config.mode != "live"
        async with self._position_lock:
            # Don't trade if we already have a position in this market
            if self._orders.has_position(market.condition_id):
                return

            # Place the trade
            trade = await self._orders.place_order(
                market=market,
                side=signal.recommended_side,
                size_usd=position_size,
                order_type=order_type,
                price_offset=config.trading.price_offset,
                is_dry_run=is_dry_run,
                signal_score=signal.composite_score,
                buy_state_snapshot=buy_state_snapshot,
                session_id=self._current_session_id,
                max_retries=config.trading.max_order_retries,
            )

        if trade:
            if trade.status == OrderStatus.REJECTED:
                logger.warning(f"🚫 Trade Rejected: {trade.notes}")
            elif trade.status == OrderStatus.CANCELLED:
                logger.warning(f"🚫 Trade Cancelled: {trade.notes}")
            else:
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
            market = self._discovery.current_market
        if signal is None:
            signal = self._last_signal

        if self._current_session_id:
            daily_stats = db.get_session_stats(self._current_session_id)
            recent_trades = db.get_trades_for_session(self._current_session_id)
            # We take top 20 for the dashboard list
            recent_trades = recent_trades[:20]
        else:
            # Fallback to daily stats if no active session
            daily_stats = db.get_daily_stats(bot_id=self._bot_id)
            recent_trades = db.get_trades(limit=20, bot_id=self._bot_id)

        # Determine effective status
        status = self._status
        if self._risk.is_in_cooldown:
            status = BotStatus.COOLDOWN

        return BotState(
            status=status,
            mode=self._cfg.config.mode,
            current_market=market,
            current_signal=signal,
            open_positions=self._orders.open_positions,
            recent_trades=recent_trades,
            daily_stats=daily_stats,
            consecutive_losses=self._risk.consecutive_losses,
            daily_pnl=self._risk.daily_pnl,
            total_pnl=self._total_pnl,
            last_updated=datetime.now(timezone.utc),
        )


# Global singleton
trading_engine = TradingEngine()
