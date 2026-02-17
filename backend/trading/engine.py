"""
Main Trading Engine.

The core loop that:
1. Discovers/rotates active 15-min BTC markets
2. Generates signals (Layer 1 + Layer 2)
3. Checks risk management
4. Places trades (or simulates in dry-run)
5. Tracks positions and resolves at market close

ASYNC version with:
- Async Binance/Polymarket client calls
- Market caching to reduce API calls
- WebSocket prices for market updates
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
    
    All I/O operations use async clients to avoid blocking.
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
        self._ws_broadcast_fn = None
        self._current_session_id: Optional[int] = None
        self._position_lock = asyncio.Lock()

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
        self._ws_broadcast_fn = fn

    async def start(self):
        if self._running:
            logger.warning("Trading engine already running")
            return

        config = self._cfg.config

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

        new_session = Session(
            start_time=datetime.now(timezone.utc),
            start_balance=db.get_state("usdc_balance", 0.0),
            status=self._status.value,
        )

        self._current_session_id = db.create_session(new_session, bot_id=self._bot_id)
        self._total_pnl = 0.0
        self._risk.reset_session_stats()

        await self._stream.start()

        self._running = True
        self._strategy_task = asyncio.create_task(self._slow_strategy_loop())
        self._risk_task = asyncio.create_task(self._fast_risk_loop())
        logger.info(f"Trading engine started in {self._status.value} mode")

    async def stop(self):
        logger.info("Stopping trading engine...")
        self._running = False

        await self._stream.stop()

        for task in [self._strategy_task, self._risk_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self._orders.cancel_all()

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

    async def _slow_strategy_loop(self):
        config = self._cfg.config.trading

        logger.info("Entering strategy loop")

        while self._running:
            try:
                loop_start = time.time()

                market = await self._ensure_active_market()
                if not market:
                    logger.debug("No active market, waiting...")
                    await asyncio.sleep(config.market_discovery_interval_seconds)
                    continue

                await self._update_market_prices(market)

                time_remaining = self._discovery.time_until_close()
                buffer_seconds = self._cfg.config.risk.stop_trading_minutes_before_close * 60
                if self._discovery.should_stop_trading(buffer_seconds=buffer_seconds):
                    remaining_str = f"{time_remaining:.0f}s" if time_remaining is not None else "unknown"
                    logger.info(
                        f"Too close to market close (remaining: {remaining_str}, "
                        f"buffer: {buffer_seconds}s), waiting for next window"
                    )
                    await asyncio.sleep(5)
                    continue

                composite_signal = await self._signals.compute_signal(market)
                self._last_signal = composite_signal

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
                            f"Bayesian gate BLOCKED: posterior={bayes_result['posterior']:.2f} "
                            f"(threshold=0.4) l1={composite_signal.l1_evidence} l2={composite_signal.l2_evidence}"
                        )
                    elif not bayes_result['fallback']:
                        logger.info(
                            f"Bayesian POSTERIOR: {bayes_result['posterior']:.2f} "
                            f"(prior={bayes_result['prior']:.2f}) "
                            f"l1={composite_signal.l1_evidence} l2={composite_signal.l2_evidence}"
                        )

                await self._maybe_trade(market, composite_signal)

                if self._orders.has_position(market.condition_id):
                    pos = self._orders._open_positions.get(market.condition_id)
                    if pos and not self._stream.is_price_fresh(pos.token_id):
                        await self._orders.update_position_prices(market.condition_id)

                if self._orders.has_position(market.condition_id):
                    position = self._orders._open_positions.get(market.condition_id)
                    if position:
                        btc_orderbook = await self._binance.get_orderbook()
                        current_btc_price = btc_orderbook.get("mid_price", 0)
                        current_btc_spread_bps = btc_orderbook.get("spread_bps", 0)
                        exit_decision = await evaluate_exit(
                            position, composite_signal,
                            config_mgr=self._cfg, mkt_discovery=self._discovery,
                            btc_client=self._binance,
                            current_btc_price=current_btc_price,
                            current_btc_spread_bps=current_btc_spread_bps,
                        )
                        if exit_decision:
                            await self._execute_exit(
                                market.condition_id,
                                exit_decision["reason"],
                                exit_decision["reason_category"],
                                effective_trailing_pct=exit_decision.get("effective_trailing_pct"),
                                time_zone=exit_decision.get("time_zone"),
                            )

                await self._broadcast_state(market, composite_signal)

                elapsed = time.time() - loop_start
                sleep_time = max(1, config.poll_interval_seconds - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Strategy loop error: {e}", exc_info=True)
                self._status = BotStatus.ERROR
                await asyncio.sleep(10)

    async def _fast_risk_loop(self):
        logger.info("Entering fast risk loop")

        while self._running:
            try:
                exit_config = self._cfg.config.exit
                if not exit_config.enabled:
                    await asyncio.sleep(1.0)
                    continue

                market = self._discovery.current_market
                if market:
                    up_mid = self._stream.prices.get_midpoint(market.up_token_id)
                    down_mid = self._stream.prices.get_midpoint(market.down_token_id)
                    if up_mid is not None:
                        market.up_price = up_mid
                    if down_mid is not None:
                        market.down_price = down_mid

                btc_orderbook = await self._binance.get_orderbook()
                current_btc_price = btc_orderbook.get("mid_price", 0)
                current_btc_spread_bps = btc_orderbook.get("spread_bps", 0)

                exited = False
                for condition_id, position in list(self._orders._open_positions.items()):
                    ws_price = self._stream.prices.get_midpoint(position.token_id)
                    if ws_price is None or not self._stream.is_price_fresh(position.token_id):
                        try:
                            ws_price = await self._polymarket.get_midpoint(position.token_id)
                        except Exception:
                            continue
                    if ws_price is None:
                        continue

                    position.current_price = ws_price
                    position.unrealized_pnl = (ws_price - position.entry_price) * position.size
                    if ws_price > position.peak_price:
                        position.peak_price = ws_price
                    if ws_price < position.trough_price or position.trough_price == 0:
                        position.trough_price = ws_price

                    if position.entry_time:
                        held = (datetime.now(timezone.utc) - position.entry_time).total_seconds()
                        if held < exit_config.min_hold_seconds:
                            continue
                    else:
                        held = 999

                    in_survival_buffer = (
                        exit_config.survival_buffer_enabled
                        and held < exit_config.survival_buffer_seconds
                    )

                    signal = self._last_signal
                    l2_confidence = signal.layer2.confidence if signal and signal.layer2 else 0.5
                    if exit_config.signal_decay_estop_enabled and l2_confidence < exit_config.signal_decay_threshold:
                        reason = (
                            f"signal_decay_estop: BTC L2 confidence={l2_confidence:.2f} < {exit_config.signal_decay_threshold:.2f} | "
                            f"OVERRIDE survival buffer, immediate exit (WS fast-check)"
                        )
                        logger.info(f"FAST EMERGENCY EXIT -- {reason}")
                        await self._execute_exit(condition_id, reason, "signal_decay_estop", time_zone="SURVIVAL")
                        exited = True
                        break

                    conviction = position.entry_conviction if position.entry_conviction > 0 else 0.5
                    if conviction >= exit_config.high_conviction_threshold:
                        conviction_tier = "high"
                        effective_tp = exit_config.high_conviction_tp_pct
                    elif conviction <= exit_config.low_conviction_threshold:
                        conviction_tier = "low"
                        effective_tp = exit_config.hard_tp_pct
                    else:
                        conviction_tier = "normal"
                        effective_tp = exit_config.hard_tp_pct

                    atr_15m_percentile = signal.atr_15m_percentile if signal else None
                    if exit_config.delta_scaling_enabled and atr_15m_percentile is not None and atr_15m_percentile > 75:
                        atr_multiplier = 1.0 + exit_config.atr_scale_factor * ((atr_15m_percentile - 50) / 50)
                        effective_tp = min(effective_tp * atr_multiplier, 0.60)

                    is_profitable = position.current_price > position.entry_price

                    if in_survival_buffer:
                        if position.current_price > 0 and position.entry_price > 0:
                            survival_hard_stop = exit_config.survival_hard_stop_bps / 10000.0
                            drop_from_entry = (position.entry_price - position.current_price) / position.entry_price
                            if drop_from_entry >= survival_hard_stop:
                                reason = (
                                    f"survival_hard_stop: price {position.current_price:.3f} dropped "
                                    f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                                    f"(survival buffer: {survival_hard_stop:.2%} for {held:.0f}s) (WS fast-check)"
                                )
                                logger.info(f"FAST EXIT -- {reason}")
                                await self._execute_exit(condition_id, reason, "hard_stop", time_zone="SURVIVAL")
                                exited = True
                                break
                        
                        divergence_blocked = False
                        if exit_config.divergence_monitor_enabled:
                            if position.entry_price > 0 and position.current_price > 0:
                                token_drop_bps = abs(position.entry_price - position.current_price) / position.entry_price * 10000
                                btc_move_bps = 0.0
                                if position.entry_btc_price > 0 and current_btc_price > 0:
                                    btc_move_bps = abs(current_btc_price - position.entry_btc_price) / position.entry_btc_price * 10000
                                
                                if token_drop_bps > exit_config.token_noise_threshold_bps and btc_move_bps < exit_config.btc_stable_threshold_bps:
                                    divergence_blocked = True
                                    logger.info(
                                        f"DIVERGENCE (fast): Token {token_drop_bps:.1f} BPS, BTC {btc_move_bps:.1f} BPS | Blocking trailing stop"
                                    )

                        liquidity_guard_active = False
                        try:
                            token_ob = await self._polymarket.get_order_book(position.token_id)
                            if token_ob:
                                bids = token_ob.get("bids", [])
                                asks = token_ob.get("asks", [])
                                if bids and asks:
                                    best_bid = float(bids[0].get("price", 0))
                                    best_ask = float(asks[0].get("price", 0))
                                    if best_bid > 0:
                                        token_spread_bps = (best_ask - best_bid) / best_bid * 10000
                                if exit_config.liquidity_guard_enabled and token_spread_bps > exit_config.token_wide_spread_bps:
                                    btc_spread_change = abs(current_btc_spread_bps - position.entry_btc_spread_bps)
                                    if btc_spread_change < exit_config.btc_spread_stable_bps:
                                        liquidity_guard_active = True
                                        logger.info(
                                            f"LIQUIDITY GUARD (fast): Token spread={token_spread_bps:.0f} BPS | Blocking trailing stop"
                                        )
                        except Exception:
                            pass

                        if divergence_blocked or liquidity_guard_active:
                            continue
                        continue

                    liquidity_guard_active = False
                    try:
                        token_ob = await self._polymarket.get_order_book(position.token_id)
                        if token_ob:
                            bids = token_ob.get("bids", [])
                            asks = token_ob.get("asks", [])
                            if bids and asks:
                                best_bid = float(bids[0].get("price", 0))
                                best_ask = float(asks[0].get("price", 0))
                                if best_bid > 0:
                                    token_spread_bps = (best_ask - best_bid) / best_bid * 10000
                            if exit_config.liquidity_guard_enabled and token_spread_bps > exit_config.token_wide_spread_bps:
                                btc_spread_change = abs(current_btc_spread_bps - position.entry_btc_spread_bps)
                                if btc_spread_change < exit_config.btc_spread_stable_bps:
                                    liquidity_guard_active = True
                                    logger.info(
                                        f"LIQUIDITY GUARD (fast): Token spread={token_spread_bps:.0f} BPS | Blocking stop-hunt"
                                    )
                    except Exception:
                        pass

                    if liquidity_guard_active:
                        continue

                    if not is_profitable:
                        if position.current_price > 0 and position.entry_price > 0:
                            drop_from_entry = (position.entry_price - position.current_price) / position.entry_price
                            if drop_from_entry >= exit_config.hard_stop_pct:
                                reason = (
                                    f"hard_stop: price {position.current_price:.3f} dropped "
                                    f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                                    f"(hard limit: {exit_config.hard_stop_pct:.0%}) (WS fast-check)"
                                )
                                logger.info(f"FAST EXIT -- {reason}")
                                await self._execute_exit(condition_id, reason, "hard_stop")
                                exited = True
                                break
                        continue

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

                    if conviction_tier == "low":
                        base_trailing = min(base_trailing, exit_config.low_conviction_trail_pct)

                    if exit_config.scaling_tp_enabled and position.entry_price > 0 and is_profitable:
                        gain_pct = (position.current_price - position.entry_price) / position.entry_price
                        stop_reduction = exit_config.scaling_tp_pct * gain_pct
                        base_trailing = base_trailing * (1.0 - stop_reduction)
                        base_trailing = max(base_trailing, exit_config.scaling_tp_min_trail)

                    if position.peak_price > 0 and position.current_price > 0:
                        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price
                        if drop_from_peak >= base_trailing:
                            reason = (
                                f"trailing_stop: price {position.current_price:.3f} dropped "
                                f"{drop_from_peak:.1%} from peak {position.peak_price:.3f} | "
                                f"effective={base_trailing:.1%} [{time_zone}] ({conviction_tier} conviction) (WS fast-check)"
                            )
                            logger.info(f"FAST EXIT -- {reason}")
                            await self._execute_exit(
                                condition_id, reason, "trailing_stop",
                                effective_trailing_pct=base_trailing,
                                time_zone=time_zone,
                            )
                            exited = True
                            break

                    if position.current_price > 0 and position.entry_price > 0:
                        drop_from_entry = (position.entry_price - position.current_price) / position.entry_price
                        if drop_from_entry >= exit_config.hard_stop_pct:
                            reason = (
                                f"hard_stop: price {position.current_price:.3f} dropped "
                                f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                                f"(hard limit: {exit_config.hard_stop_pct:.0%}) (WS fast-check)"
                            )
                            logger.info(f"FAST EXIT -- {reason}")
                            await self._execute_exit(condition_id, reason, "hard_stop")
                            exited = True
                            break

                    if exit_config.hard_tp_enabled and position.entry_price > 0 and position.current_price > 0:
                        gain_from_entry = (position.current_price - position.entry_price) / position.entry_price
                        if gain_from_entry >= effective_tp:
                            reason = (
                                f"hard_take_profit: price {position.current_price:.3f} rose "
                                f"{gain_from_entry:.1%} from entry {position.entry_price:.3f} "
                                f"(TP limit: {effective_tp:.0%}, {conviction_tier} conviction) (WS fast-check)"
                            )
                            logger.info(f"FAST EXIT -- {reason}")
                            await self._execute_exit(condition_id, reason, "hard_take_profit")
                            exited = True
                            break

                    if conviction_tier == "low" and position.current_price > position.entry_price:
                        tick = 0.01
                        target_price = position.current_price + tick
                        if position.current_price >= target_price - tick:
                            reason = (
                                f"low_conviction_take_profit: conviction={conviction:.2f} < {exit_config.low_conviction_threshold:.2f} | "
                                f"securing win at {position.current_price:.3f} (WS fast-check)"
                            )
                            logger.info(f"FAST EXIT -- {reason}")
                            await self._execute_exit(condition_id, reason, "hard_take_profit")
                            exited = True
                            break

                await asyncio.sleep(1.0 if exited else 0.25)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Fast risk loop error: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _execute_exit(
        self,
        condition_id: str,
        reason: str,
        reason_category: str,
        effective_trailing_pct: Optional[float] = None,
        time_zone: Optional[str] = None,
    ):
        async with self._position_lock:
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
                    sell_state = await self._capture_market_state(market, signal)
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
                    f"Early exit ({reason_category}): "
                    f"P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}"
                )
                
                if self._cfg.config.bayesian.enabled and self._bayesian_mgr and self._last_signal:
                    won = pnl > 0
                    self._bayesian_mgr.record_outcome(
                        self._last_signal.l1_evidence,
                        self._last_signal.l2_evidence,
                        won,
                    )

    async def _ensure_active_market(self) -> Optional[MarketInfo]:
        market = await self._discovery.scan_for_active_market()

        if market and market.condition_id != self._previous_market_id:
            if self._previous_market_id:
                await self._handle_market_close(self._previous_market_id)
                self._risk.on_market_change(market.condition_id)

            self._previous_market_id = market.condition_id
            logger.info(f"Active market: {market.question}")

            tokens = [t for t in [market.up_token_id, market.down_token_id] if t]
            if tokens:
                self._stream.subscribe(tokens)

        return market

    async def _update_market_prices(self, market: MarketInfo):
        """Update market prices, preferring WebSocket data when fresh."""
        try:
            up_mid = self._stream.prices.get_midpoint(market.up_token_id)
            down_mid = self._stream.prices.get_midpoint(market.down_token_id)
            
            if up_mid is not None and self._stream.is_price_fresh(market.up_token_id):
                market.up_price = up_mid
            else:
                market.up_price = await self._polymarket.get_midpoint(market.up_token_id)
            
            if down_mid is not None and self._stream.is_price_fresh(market.down_token_id):
                market.down_price = down_mid
            else:
                market.down_price = await self._polymarket.get_midpoint(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error updating market prices: {e}")

    @staticmethod
    def compute_orderbook_imbalance(orderbook: dict) -> dict:
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        bid_vol_5 = sum(float(b.get("size", 0)) for b in bids[:5])
        ask_vol_5 = sum(float(a.get("size", 0)) for a in asks[:5])
        total_5 = bid_vol_5 + ask_vol_5

        bid_vol_10 = sum(float(b.get("size", 0)) for b in bids[:10])
        ask_vol_10 = sum(float(a.get("size", 0)) for a in asks[:10])
        total_10 = bid_vol_10 + ask_vol_10

        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 0
        
        spread = (best_ask - best_bid) if best_bid and best_ask else 0
        spread_bps = (spread / best_bid * 10000) if best_bid > 0 else 0
        
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

    async def _capture_market_state(
        self,
        market: MarketInfo,
        signal: CompositeSignal,
    ) -> MarketStateSnapshot:
        """Capture market state asynchronously."""
        timestamp = datetime.now(timezone.utc)
        
        orderbook_up = {}
        orderbook_down = {}
        try:
            if market.up_token_id:
                orderbook_up = await self._polymarket.get_order_book(market.up_token_id)
        except Exception as e:
            logger.debug(f"Error capturing up token orderbook: {e}")
        
        try:
            if market.down_token_id:
                orderbook_down = await self._polymarket.get_order_book(market.down_token_id)
        except Exception as e:
            logger.debug(f"Error capturing down token orderbook: {e}")
        
        btc_price = None
        btc_candles_summary = {}
        try:
            btc_price = await self._binance.get_current_price()
            candles = await self._binance.fetch_all_timeframes()
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
        
        risk_state = self._risk.get_state()
        
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
        if not self._orders.has_position(old_condition_id):
            return

        position = [p for p in self._orders.open_positions
                     if p.market_condition_id == old_condition_id]
        if not position:
            return

        pos = position[0]

        market = self._discovery.current_market
        if not market or market.condition_id != old_condition_id:
            trades = db.get_trades_for_market(old_condition_id)
            if trades:
                trade = trades[0]
                from models import MarketInfo
                if pos.side == Side.UP:
                    market = MarketInfo(
                        condition_id=old_condition_id,
                        question="Market Closing",
                        up_token_id=pos.token_id,
                        down_token_id="",
                    )
                else:
                    market = MarketInfo(
                        condition_id=old_condition_id,
                        question="Market Closing",
                        up_token_id="",
                        down_token_id=pos.token_id,
                    )
            else:
                from models import MarketInfo
                market = MarketInfo(
                    condition_id=old_condition_id,
                    question="Market Closing",
                    up_token_id=pos.token_id if pos.side == Side.UP else "",
                    down_token_id=pos.token_id if pos.side == Side.DOWN else "",
                )

        resolution = 0.5

        try:
            market_data = await self._polymarket.get_market(old_condition_id)
            
            if market_data and (market_data.get("closed") or market_data.get("resolved")):
                tokens = market_data.get("tokens", [])
                winner_found = False
                
                for t in tokens:
                    if t.get("winner") is True:
                        winner_found = True
                        if t.get("token_id") == pos.token_id:
                            resolution = 1.0
                        else:
                            resolution = 0.0
                        break
                
                if not winner_found:
                    logger.warning(f"Market {old_condition_id} closed but no winner flag found in tokens")
            
            if resolution == 0.5:
                final_price = await self._polymarket.get_midpoint(pos.token_id)
                if final_price > 0.9:
                    resolution = 1.0
                elif final_price < 0.1:
                    resolution = 0.0
                
        except Exception as e:
            logger.error(f"Error determining resolution for {old_condition_id}: {e}")
            resolution = 0.5

        minimal_signal = CompositeSignal(
            composite_score=0.0,
            timestamp=datetime.now(timezone.utc),
        )
        sell_state_snapshot = await self._capture_market_state(market, minimal_signal)

        pnl = self._orders.resolve_position(
            old_condition_id,
            resolution,
            sell_state_snapshot=sell_state_snapshot,
        )
        if pnl is not None:
            self._risk.record_trade_result(pnl, old_condition_id)
            self._total_pnl += pnl
            logger.info(f"Position resolved: P&L = ${pnl:.2f} | Total: ${self._total_pnl:.2f}")
            
            if self._cfg.config.bayesian.enabled and self._bayesian_mgr and self._last_signal:
                won = pnl > 0
                self._bayesian_mgr.record_outcome(
                    self._last_signal.l1_evidence,
                    self._last_signal.l2_evidence,
                    won,
                )

    async def _maybe_trade(self, market: MarketInfo, signal: CompositeSignal):
        config = self._cfg.config

        allowed, reason = self._risk.can_trade(signal, market.condition_id)
        if not allowed:
            logger.debug(f"Trade blocked: {reason}")
            return

        if config.bayesian.enabled and not signal.bayesian_confidence_gate:
            logger.info(
                f"Trade blocked by Bayesian confidence gate: "
                f"posterior={signal.bayesian_posterior:.2f} < threshold=0.4"
            )
            return

        max_entry = config.risk.max_entry_price
        current_price = 0.5
        if signal.recommended_side == Side.UP:
            current_price = market.up_price if market.up_price else 0.5
        elif signal.recommended_side == Side.DOWN:
            current_price = market.down_price if market.down_price else 0.5

        if current_price > max_entry:
            logger.info(f"Trade Skipped: Price {current_price:.2f} exceeds max entry {max_entry:.2f}")
            return

        position_size = self._risk.get_position_size()
        if position_size <= 0:
            logger.debug("Position size is 0, can't trade")
            return

        order_type = config.trading.order_type
        if (
            config.trading.use_fok_for_strong_signals
            and abs(signal.composite_score) >= config.trading.strong_signal_threshold
        ):
            order_type = "market"

        buy_state_snapshot = await self._capture_market_state(market, signal)

        btc_orderbook = await self._binance.get_orderbook()
        current_btc_price = btc_orderbook.get("mid_price", 0)
        current_btc_spread_bps = btc_orderbook.get("spread_bps", 0)

        is_dry_run = config.mode != "live"
        async with self._position_lock:
            if self._orders.has_position(market.condition_id):
                return

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
                entry_conviction=signal.composite_confidence,
                entry_btc_price=current_btc_price,
                entry_btc_spread_bps=current_btc_spread_bps,
            )

        if trade:
            if trade.status == OrderStatus.REJECTED:
                logger.warning(f"Trade Rejected: {trade.notes}")
            elif trade.status == OrderStatus.CANCELLED:
                logger.warning(f"Trade Cancelled: {trade.notes}")
            else:
                mode_str = "DRY RUN" if is_dry_run else "LIVE"
                logger.info(
                    f"{'DRY RUN' if is_dry_run else 'LIVE'}: "
                    f"{signal.recommended_side.value.upper()} "
                    f"${position_size:.2f} @ {trade.price:.3f} "
                    f"(signal={signal.composite_score:+.3f})"
                )

    async def _broadcast_state(self, market: MarketInfo, signal: CompositeSignal):
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
        if market is None:
            market = self._discovery.current_market
        if signal is None:
            signal = self._last_signal

        if self._current_session_id:
            daily_stats = db.get_session_stats(self._current_session_id)
            recent_trades = db.get_trades_for_session(self._current_session_id)
            recent_trades = recent_trades[:20]
        else:
            daily_stats = db.get_daily_stats(bot_id=self._bot_id)
            recent_trades = db.get_trades(limit=20, bot_id=self._bot_id)

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


trading_engine = TradingEngine()