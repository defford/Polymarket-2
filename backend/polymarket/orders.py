"""
Order management for Polymarket.
Handles order placement with fee awareness, dry-run mode, and position tracking.
"""

import asyncio
import logging
import json
import time
from datetime import datetime, timezone
from typing import Optional

from models import Trade, Position, Side, OrderStatus, MarketInfo, MarketStateSnapshot
from polymarket.client import polymarket_client
import database as db

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order placement, position tracking, and P&L."""

    def __init__(self, polymarket_cli=None, bot_id: Optional[int] = None):
        self._polymarket_cli = polymarket_cli  # None = use global
        self._bot_id = bot_id
        self._open_positions: dict[str, Position] = {}  # condition_id -> Position
        self._pending_orders: dict[str, Trade] = {}  # order_id -> Trade

    @property
    def _pm_client(self):
        return self._polymarket_cli if self._polymarket_cli is not None else polymarket_client

    @property
    def open_positions(self) -> list[Position]:
        return list(self._open_positions.values())

    def has_position(self, condition_id: str) -> bool:
        return condition_id in self._open_positions

    async def place_order(
        self,
        market: MarketInfo,
        side: Side,
        size_usd: float,
        order_type: str = "postOnly",  # "postOnly", "limit", "market"
        price_offset: float = 0.01,
        is_dry_run: bool = True,
        signal_score: float = 0.0,
        buy_state_snapshot: Optional[MarketStateSnapshot] = None,
        session_id: Optional[int] = None,
        max_retries: int = 5,
    ) -> Optional[Trade]:
        """
        Place an order on the active market.

        Args:
            market: The active market info
            side: UP or DOWN
            size_usd: How much to spend in USDC
            order_type: "postOnly", "limit", or "market"
            price_offset: Offset from best price for limit orders
            is_dry_run: If True, don't actually place the order
            signal_score: The signal strength that triggered this trade
            max_retries: Number of seconds to wait for a fill (1 retry/sec)

        Returns:
            Trade object if successful, None otherwise
        """
        # Determine which token to buy
        token_id = market.up_token_id if side == Side.UP else market.down_token_id

        # Get current price
        try:
            best_price = self._pm_client.get_price(token_id, side="BUY")
        except Exception:
            best_price = 0.5

        if best_price <= 0 or best_price >= 1:
            logger.warning(f"Invalid price {best_price} for {side.value} token")
            return None

        # Calculate size in tokens
        if order_type == "market":
            price = best_price
        else:
            # For limit/postOnly, place slightly better than best ask
            price = round(best_price - price_offset, 2)
            price = max(0.01, min(0.99, price))

        size_tokens = size_usd / price

        # Estimate fees (up to 3% taker on 15-min markets)
        estimated_fee = 0.0
        if order_type == "market":
            # Taker fee varies, estimate conservatively at 2%
            estimated_fee = size_usd * 0.02
        elif order_type != "postOnly":
            # Regular limit could be taker if marketable
            estimated_fee = size_usd * 0.01

        # Create trade record
        trade = Trade(
            timestamp=datetime.now(timezone.utc),
            market_condition_id=market.condition_id,
            side=side,
            token_id=token_id,
            price=price,
            size=size_tokens,
            cost=size_usd,
            fees=estimated_fee,
            is_dry_run=is_dry_run,
            signal_score=signal_score,
            status=OrderStatus.PENDING,
            session_id=session_id,
        )

        # Track the price we requested (before fill changes it)
        requested_price = price

        # Prepare trade log data with buy state
        trade_log_data = None
        if buy_state_snapshot:
            try:
                log_entry = {
                    "buy_state": buy_state_snapshot.model_dump(mode="json"),
                    "order_type": order_type,
                    "position_size_usd": size_usd,
                }

                # Compute order book imbalance at entry
                try:
                    from trading.engine import TradingEngine
                    ob_key = "orderbook_up" if side == Side.UP else "orderbook_down"
                    entry_ob = getattr(buy_state_snapshot, ob_key, {})
                    if entry_ob:
                        log_entry["orderbook_imbalance_entry"] = TradingEngine.compute_orderbook_imbalance(entry_ob)
                except Exception as e:
                    logger.debug(f"Error computing entry OBI: {e}")

                trade_log_data = json.dumps(log_entry, default=str)
            except Exception as e:
                logger.debug(f"Error serializing buy state: {e}")

        if is_dry_run:
            # Simulate fill immediately in dry run
            trade.status = OrderStatus.FILLED
            trade.order_id = f"dry_run_{int(datetime.now().timestamp() * 1000)}"
            trade.notes = f"DRY RUN: {order_type} {side.value} {size_tokens:.2f} tokens @ {price}"
            logger.info(f"🧪 DRY RUN: {trade.notes}")

            # Track position
            self._open_positions[market.condition_id] = Position(
                market_condition_id=market.condition_id,
                side=side,
                token_id=token_id,
                entry_price=price,
                size=size_tokens,
                cost=size_usd,
                current_price=price,
                peak_price=price,
                trough_price=price,
                entry_time=datetime.now(timezone.utc),
                is_dry_run=True,
            )

            # Add fill info and slippage for dry run (zero slippage)
            if trade_log_data:
                try:
                    log_entry = json.loads(trade_log_data)
                    log_entry["entry_slippage"] = {
                        "requested_price": requested_price,
                        "fill_price": price,
                        "slippage_bps": 0.0,
                        "order_type": order_type,
                    }
                    log_entry["fill_info"] = {
                        "order_type": order_type,
                        "was_fok": order_type == "market",
                        "fill_status": "filled",
                        "time_to_fill_seconds": 0.0,
                        "retries": 0,
                        "requested_size": size_tokens,
                    }
                    trade_log_data = json.dumps(log_entry, default=str)
                except Exception:
                    pass

            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
            return trade

        # --- Live order placement ---
        try:
            if order_type == "market":
                resp = self._pm_client.place_market_order(
                    token_id=token_id,
                    amount=size_usd,
                    side="BUY",
                )
            else:
                resp = self._pm_client.place_limit_order(
                    token_id=token_id,
                    price=price,
                    size=size_tokens,
                    side="BUY",
                    post_only=(order_type == "postOnly"),
                )

            if resp.get("success") or resp.get("orderID"):
                trade.order_id = resp.get("orderID", resp.get("order_id", "unknown"))

                # VERIFY ORDER STATUS (Fix for Ghost Trades)
                # Ensure the order wasn't rejected or immediately cancelled
                fill_start_time = time.time()
                fill_retries = 0
                fill_status = "unknown"
                try:
                    # Poll for fill for up to max_retries seconds (non-blocking)
                    filled = False

                    for i in range(max_retries):
                        fill_retries = i + 1
                        await asyncio.sleep(1.0)
                        order_check = self._pm_client.get_order(trade.order_id)
                        order_status = order_check.get("status") if order_check else "UNKNOWN"

                        if order_status == "FILLED":
                            filled = True
                            # Try to get avg fill price
                            if "avgPrice" in order_check:
                                price = float(order_check["avgPrice"])
                            elif "matchedAvgPrice" in order_check:
                                price = float(order_check["matchedAvgPrice"])
                            break
                        elif order_status in ("CANCELED", "KILLED", "REJECTED"):
                            logger.warning(f"❌ Order {trade.order_id} was {order_status}. Not counting as trade.")
                            trade.status = OrderStatus.REJECTED
                            trade.notes = f"REJECTED: Order status {order_status}"
                            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
                            return None

                        # If OPEN, we wait and retry.

                    if not filled:
                        logger.info(f"⏳ Order {trade.order_id} still OPEN after {max_retries}s. Cancelling...")

                        # Attempt to cancel
                        cancel_resp = self._pm_client.cancel_order(trade.order_id)

                        if cancel_resp and cancel_resp.get("success"):
                            trade.status = OrderStatus.CANCELLED
                            trade.notes = f"CANCELLED: Timed out waiting for fill"
                            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
                            logger.info(f"🚫 Cancelled order {trade.order_id} successfully.")
                            return None
                        else:
                            # Cancellation failed — check if it filled in the meantime
                            logger.warning(f"⚠️ Cancel failed for {trade.order_id} (msg={cancel_resp}). Checking if it filled...")
                            await asyncio.sleep(0.5)
                            final_check = self._pm_client.get_order(trade.order_id)
                            final_status = final_check.get("status") if final_check else "UNKNOWN"

                            if final_status == "FILLED":
                                logger.info(f"✅ Order {trade.order_id} actually FILLED! Recovering trade.")
                                filled = True
                                if "avgPrice" in final_check:
                                    price = float(final_check["avgPrice"])
                                elif "matchedAvgPrice" in final_check:
                                    price = float(final_check["matchedAvgPrice"])
                            elif final_status == "CANCELED":
                                trade.status = OrderStatus.CANCELLED
                                trade.notes = f"CANCELLED: Timed out waiting for fill"
                                trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
                                return None
                            else:
                                logger.error(f"❌ Order {trade.order_id} state ambiguous ({final_status}). Marking as CANCELLED.")
                                trade.status = OrderStatus.CANCELLED
                                trade.notes = f"AMBIGUOUS: Cancel failed but status is {final_status}"
                                trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
                                return None

                    # If we get here, it is FILLED
                    trade.status = OrderStatus.FILLED
                    fill_status = "filled"

                except Exception as e:
                    logger.warning(f"Could not verify order {trade.order_id}: {e}")
                    # Assume FILLED to prevent orphaned positions — market close will reconcile
                    trade.status = OrderStatus.FILLED
                    fill_status = "unverified"
                    trade.notes = f"UNVERIFIED: API error during verification ({e})"
                    logger.warning("⚠️ Assuming FILLED to prevent orphaned positions")

                trade.notes = f"LIVE: {order_type} {side.value} {size_tokens:.2f} @ {price}"
                logger.info(f"✅ LIVE ORDER: {trade.notes} (id={trade.order_id})")

                # Enrich trade log with slippage and fill info
                actual_fill_price = price  # price may have been updated from avgPrice
                if trade_log_data:
                    try:
                        log_entry = json.loads(trade_log_data)
                        slippage_bps = 0.0
                        if requested_price > 0:
                            slippage_bps = (actual_fill_price - requested_price) / requested_price * 10000
                        log_entry["entry_slippage"] = {
                            "requested_price": requested_price,
                            "fill_price": actual_fill_price,
                            "slippage_bps": round(slippage_bps, 2),
                            "order_type": order_type,
                        }
                        log_entry["fill_info"] = {
                            "order_type": order_type,
                            "was_fok": order_type == "market",
                            "fill_status": fill_status,
                            "time_to_fill_seconds": round(time.time() - fill_start_time, 2),
                            "retries": fill_retries,
                            "requested_size": size_tokens,
                        }
                        trade_log_data = json.dumps(log_entry, default=str)
                    except Exception as e:
                        logger.debug(f"Error enriching trade log with fill data: {e}")

                self._open_positions[market.condition_id] = Position(
                    market_condition_id=market.condition_id,
                    side=side,
                    token_id=token_id,
                    entry_price=price,
                    size=size_tokens,
                    cost=size_usd,
                    current_price=price,
                    peak_price=price,
                    trough_price=price,
                    entry_time=datetime.now(timezone.utc),
                    is_dry_run=False,
                )
            else:
                error = resp.get("errorMsg", "Unknown error")
                trade.status = OrderStatus.REJECTED
                trade.notes = f"REJECTED: {error}"
                logger.warning(f"❌ Order rejected: {error}")

            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
            return trade

        except Exception as e:
            trade.status = OrderStatus.REJECTED
            trade.notes = f"ERROR: {str(e)}"
            logger.error(f"❌ Order error: {e}")
            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data, bot_id=self._bot_id)
            return trade

    def resolve_position(
        self,
        condition_id: str,
        resolution_price: float,
        sell_state_snapshot: Optional[MarketStateSnapshot] = None,
    ) -> Optional[float]:
        """
        Resolve a position when the 15-min market closes.
        
        For Up/Down markets:
        - If you bought "Up" and BTC went up → token worth $1.00
        - If you bought "Up" and BTC went down → token worth $0.00
        
        Returns P&L or None if no position.
        """
        position = self._open_positions.get(condition_id)
        if not position:
            return None

        # In binary markets, winning token = $1.00, losing = $0.00
        # resolution_price is 1.0 (won) or 0.0 (lost) for the token we hold
        payout = position.size * resolution_price
        pnl = payout - position.cost

        logger.info(
            f"Position resolved: {position.side.value} "
            f"entry={position.entry_price:.3f} "
            f"size={position.size:.2f} "
            f"payout=${payout:.2f} "
            f"P&L=${pnl:.2f}"
        )

        # Update trade record in DB with sell state and P&L
        trades = db.get_trades_for_market(condition_id)
        for trade in trades:
            # Filter by bot_id to prevent cross-talk in swarm mode
            if self._bot_id is not None and trade.bot_id != self._bot_id:
                continue

            if trade.status == OrderStatus.FILLED and trade.pnl is None:
                # Load existing trade log data
                existing_log_data = db.get_trade_log_data(trade.id)
                log_entry = {}
                
                if existing_log_data:
                    try:
                        log_entry = json.loads(existing_log_data)
                    except Exception as e:
                        logger.debug(f"Error parsing existing log data: {e}")
                
                # Add sell state and calculate duration
                if sell_state_snapshot:
                    log_entry["sell_state"] = sell_state_snapshot.model_dump(mode="json")
                    
                    # Calculate position held duration
                    if "buy_state" in log_entry and log_entry["buy_state"].get("timestamp"):
                        try:
                            buy_time = datetime.fromisoformat(log_entry["buy_state"]["timestamp"])
                            sell_time = sell_state_snapshot.timestamp
                            duration = (sell_time - buy_time).total_seconds()
                            log_entry["position_held_duration_seconds"] = duration
                        except Exception as e:
                            logger.debug(f"Error calculating duration: {e}")
                
                log_entry["pnl"] = pnl
                log_entry["resolution_price"] = resolution_price

                # Exit metadata for market close
                log_entry["exit_reason"] = "market_close"
                log_entry["exit_price"] = resolution_price
                log_entry["peak_price"] = position.peak_price
                log_entry["drawdown_from_peak"] = (
                    (position.peak_price - position.current_price) / position.peak_price
                    if position.peak_price > 0 else 0.0
                )
                log_entry["time_remaining_at_exit"] = 0

                # MAE/MFE tracking
                if position.entry_price > 0:
                    mae_pct = (position.entry_price - position.trough_price) / position.entry_price if position.trough_price > 0 else 0
                    mfe_pct = (position.peak_price - position.entry_price) / position.entry_price if position.peak_price > 0 else 0
                    actual_return = (resolution_price - position.entry_price) / position.entry_price
                    log_entry["mae_mfe"] = {
                        "entry_price": position.entry_price,
                        "peak_price": position.peak_price,
                        "trough_price": position.trough_price,
                        "exit_price": resolution_price,
                        "mae_pct": round(mae_pct, 6),
                        "mfe_pct": round(mfe_pct, 6),
                        "actual_return_pct": round(actual_return, 6),
                        "capture_ratio": round(actual_return / mfe_pct, 4) if mfe_pct > 0 else 0,
                    }

                # Order book imbalance at exit
                if sell_state_snapshot:
                    try:
                        from trading.engine import TradingEngine
                        ob_key = "orderbook_up" if position.side == Side.UP else "orderbook_down"
                        exit_ob = getattr(sell_state_snapshot, ob_key, {})
                        if exit_ob:
                            log_entry["orderbook_imbalance_exit"] = TradingEngine.compute_orderbook_imbalance(exit_ob)
                    except Exception as e:
                        logger.debug(f"Error computing exit OBI: {e}")

                # Update trade log data
                updated_log_data = json.dumps(log_entry, default=str)
                db.update_trade(trade.id, pnl=pnl, status="filled", trade_log_data=updated_log_data)

        # Close position
        del self._open_positions[condition_id]
        return pnl

    async def sell_position(
        self,
        condition_id: str,
        reason: str = "stop_loss",
        is_dry_run: bool = True,
        sell_state_snapshot: Optional[MarketStateSnapshot] = None,
    ) -> Optional[float]:
        """
        Sell an open position early (before market resolution).

        Places a SELL order for the tokens we hold. Updates the existing
        buy trade record with exit metadata (same pattern as resolve_position).

        Args:
            condition_id: The market to sell from
            reason: Why we're selling (full reason string from exit strategy)
            is_dry_run: Whether to simulate
            sell_state_snapshot: Market state at time of exit

        Returns:
            P&L from the early exit, or None if failed
        """
        position = self._open_positions.get(condition_id)
        if not position:
            logger.warning(f"No position to sell for {condition_id[:16]}...")
            return None

        # Get current sell price
        try:
            sell_price = self._pm_client.get_price(position.token_id, side="SELL")
        except Exception:
            sell_price = position.current_price

        if sell_price <= 0:
            logger.warning(f"Invalid sell price {sell_price}, using current_price")
            sell_price = position.current_price

        # Track requested sell price before fill may change it
        requested_sell_price = sell_price

        # Calculate proceeds and P&L
        proceeds = sell_price * position.size
        estimated_fee = proceeds * 0.02  # conservative taker fee estimate
        net_proceeds = proceeds - estimated_fee
        pnl = net_proceeds - position.cost

        # Parse exit reason category
        exit_reason = _parse_exit_reason(reason)

        if is_dry_run:
            logger.info(
                f"🧪🔴 DRY RUN EXIT ({exit_reason}): "
                f"SELL {position.side.value.upper()} "
                f"{position.size:.2f} tokens @ {sell_price:.3f} | "
                f"Entry: {position.entry_price:.3f} | Peak: {position.peak_price:.3f} | "
                f"Proceeds: ${net_proceeds:.2f} | P&L: ${pnl:+.2f}"
            )
        else:
            # Live sell
            try:
                resp = self._pm_client.place_market_order(
                    token_id=position.token_id,
                    amount=position.size,
                    side="SELL",
                )
                if not (resp.get("success") or resp.get("orderID")):
                    error = resp.get("errorMsg", "Unknown error")
                    logger.warning(f"❌ Exit sell rejected: {error}")
                    return None

                order_id = resp.get("orderID", resp.get("order_id", "unknown"))
                
                # UPDATE WITH ACTUAL FILL PRICE
                try:
                    await asyncio.sleep(1.0)  # Wait for fill
                    order_details = self._pm_client.get_order(order_id)
                    actual_price = None
                    
                    # Try to find average fill price in order details
                    # Note: Field names vary by API version (avgPrice, price, matchedAvgPrice)
                    if order_details:
                        if "avgPrice" in order_details:
                            actual_price = float(order_details["avgPrice"])
                        elif "matchedAvgPrice" in order_details:
                            actual_price = float(order_details["matchedAvgPrice"])
                    
                    if actual_price and actual_price > 0:
                        logger.info(f"Refining exit price: {sell_price:.3f} -> {actual_price:.3f}")
                        sell_price = actual_price
                        
                        # Recalculate P&L with actual price
                        proceeds = sell_price * position.size
                        estimated_fee = proceeds * 0.02  # Keep conservative fee estimate
                        net_proceeds = proceeds - estimated_fee
                        pnl = net_proceeds - position.cost
                        
                except Exception as e:
                    logger.warning(f"Could not fetch actual fill price for {order_id}, using estimate: {e}")

                logger.info(
                    f"🔴 LIVE EXIT ({exit_reason}): "
                    f"SELL {position.side.value.upper()} "
                    f"{position.size:.2f} tokens @ {sell_price:.3f} | "
                    f"P&L: ${pnl:+.2f} (id={order_id})"
                )
            except Exception as e:
                logger.error(f"❌ Exit sell error: {e}")
                return None

        # Update the existing buy trade record with exit data
        trades = db.get_trades_for_market(condition_id)
        for trade in trades:
            # Filter by bot_id to prevent cross-talk in swarm mode
            if self._bot_id is not None and trade.bot_id != self._bot_id:
                continue

            if trade.status == OrderStatus.FILLED and trade.pnl is None:
                existing_log_data = db.get_trade_log_data(trade.id)
                log_entry = {}

                if existing_log_data:
                    try:
                        log_entry = json.loads(existing_log_data)
                    except Exception as e:
                        logger.debug(f"Error parsing existing log data: {e}")

                # Add sell state
                if sell_state_snapshot:
                    log_entry["sell_state"] = sell_state_snapshot.model_dump(mode="json")

                    # Calculate position held duration
                    if "buy_state" in log_entry and log_entry["buy_state"].get("timestamp"):
                        try:
                            buy_time = datetime.fromisoformat(log_entry["buy_state"]["timestamp"])
                            sell_time = sell_state_snapshot.timestamp
                            duration = (sell_time - buy_time).total_seconds()
                            log_entry["position_held_duration_seconds"] = duration
                        except Exception as e:
                            logger.debug(f"Error calculating duration: {e}")

                # Exit metadata
                log_entry["pnl"] = pnl
                log_entry["exit_reason"] = exit_reason
                log_entry["exit_reason_detail"] = reason
                log_entry["exit_price"] = sell_price
                log_entry["peak_price"] = position.peak_price
                log_entry["drawdown_from_peak"] = (
                    (position.peak_price - position.current_price) / position.peak_price
                    if position.peak_price > 0 else 0.0
                )

                # Time remaining at exit
                time_remaining = None
                if sell_state_snapshot and sell_state_snapshot.market_window_info:
                    time_remaining = sell_state_snapshot.market_window_info.get(
                        "time_until_close_seconds"
                    )
                log_entry["time_remaining_at_exit"] = time_remaining

                # Exit slippage (dry run = 0, live = diff between requested and actual)
                exit_slippage_bps = 0.0
                if not is_dry_run and requested_sell_price > 0:
                    exit_slippage_bps = (sell_price - requested_sell_price) / requested_sell_price * 10000
                log_entry["exit_slippage"] = {
                    "requested_price": requested_sell_price,
                    "fill_price": sell_price,
                    "slippage_bps": round(exit_slippage_bps, 2),
                }

                # MAE/MFE tracking
                if position.entry_price > 0:
                    mae_pct = (position.entry_price - position.trough_price) / position.entry_price if position.trough_price > 0 else 0
                    mfe_pct = (position.peak_price - position.entry_price) / position.entry_price if position.peak_price > 0 else 0
                    actual_return = (sell_price - position.entry_price) / position.entry_price
                    log_entry["mae_mfe"] = {
                        "entry_price": position.entry_price,
                        "peak_price": position.peak_price,
                        "trough_price": position.trough_price,
                        "exit_price": sell_price,
                        "mae_pct": round(mae_pct, 6),
                        "mfe_pct": round(mfe_pct, 6),
                        "actual_return_pct": round(actual_return, 6),
                        "capture_ratio": round(actual_return / mfe_pct, 4) if mfe_pct > 0 else 0,
                    }

                # Order book imbalance at exit
                if sell_state_snapshot:
                    try:
                        from trading.engine import TradingEngine
                        ob_key = "orderbook_up" if position.side == Side.UP else "orderbook_down"
                        exit_ob = getattr(sell_state_snapshot, ob_key, {})
                        if exit_ob:
                            log_entry["orderbook_imbalance_exit"] = TradingEngine.compute_orderbook_imbalance(exit_ob)
                    except Exception as e:
                        logger.debug(f"Error computing exit OBI: {e}")

                updated_log_data = json.dumps(log_entry, default=str)
                db.update_trade(
                    trade.id,
                    pnl=pnl,
                    fees=estimated_fee,
                    status="filled",
                    trade_log_data=updated_log_data,
                )
                break  # Only update the first matching trade

        # Close position
        del self._open_positions[condition_id]
        return pnl

    def update_position_prices(self, condition_id: str):
        """Update current price and peak price for an open position."""
        position = self._open_positions.get(condition_id)
        if not position:
            return

        try:
            current_price = self._pm_client.get_midpoint(position.token_id)
            position.current_price = current_price
            position.unrealized_pnl = (current_price - position.entry_price) * position.size

            # Track high-water mark for trailing stop
            if current_price > position.peak_price:
                position.peak_price = current_price
        except Exception as e:
            logger.debug(f"Could not update position price: {e}")

    def cancel_all(self):
        """Cancel all open orders (live mode only)."""
        if self._pm_client.is_authenticated:
            try:
                self._pm_client.cancel_all_orders()
                logger.info("All open orders cancelled")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")


def _parse_exit_reason(reason: str) -> str:
    """Parse a detailed exit reason string into a category."""
    reason_lower = reason.lower()
    if reason_lower.startswith("trailing_stop"):
        return "trailing_stop"
    elif reason_lower.startswith("hard_stop"):
        return "hard_stop"
    elif reason_lower.startswith("signal_reversal"):
        return "signal_reversal"
    elif reason_lower.startswith("market_close"):
        return "market_close"
    return "unknown"


# Global singleton
order_manager = OrderManager()
