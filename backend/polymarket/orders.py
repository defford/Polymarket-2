"""
Order management for Polymarket.
Handles order placement with fee awareness, dry-run mode, and position tracking.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional

from models import Trade, Position, Side, OrderStatus, MarketInfo, MarketStateSnapshot
from polymarket.client import polymarket_client
import database as db

logger = logging.getLogger(__name__)


class OrderManager:
    """Manages order placement, position tracking, and P&L."""

    def __init__(self):
        self._open_positions: dict[str, Position] = {}  # condition_id -> Position
        self._pending_orders: dict[str, Trade] = {}  # order_id -> Trade

    @property
    def open_positions(self) -> list[Position]:
        return list(self._open_positions.values())

    def has_position(self, condition_id: str) -> bool:
        return condition_id in self._open_positions

    def place_order(
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

        Returns:
            Trade object if successful, None otherwise
        """
        # Determine which token to buy
        token_id = market.up_token_id if side == Side.UP else market.down_token_id

        # Get current price
        try:
            best_price = polymarket_client.get_price(token_id, side="BUY")
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

        # Prepare trade log data with buy state
        trade_log_data = None
        if buy_state_snapshot:
            try:
                log_entry = {
                    "buy_state": buy_state_snapshot.model_dump(mode="json"),
                    "order_type": order_type,
                    "position_size_usd": size_usd,
                }
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
                entry_time=datetime.now(timezone.utc),
                is_dry_run=True,
            )

            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data)
            return trade

        # --- Live order placement ---
        try:
            if order_type == "market":
                resp = polymarket_client.place_market_order(
                    token_id=token_id,
                    amount=size_usd,
                    side="BUY",
                )
            else:
                resp = polymarket_client.place_limit_order(
                    token_id=token_id,
                    price=price,
                    size=size_tokens,
                    side="BUY",
                    post_only=(order_type == "postOnly"),
                )

            if resp.get("success") or resp.get("orderID"):
                trade.order_id = resp.get("orderID", resp.get("order_id", "unknown"))
                trade.status = OrderStatus.FILLED  # Simplified; real impl would check
                trade.notes = f"LIVE: {order_type} {side.value} {size_tokens:.2f} @ {price}"
                logger.info(f"✅ LIVE ORDER: {trade.notes} (id={trade.order_id})")

                self._open_positions[market.condition_id] = Position(
                    market_condition_id=market.condition_id,
                    side=side,
                    token_id=token_id,
                    entry_price=price,
                    size=size_tokens,
                    cost=size_usd,
                    current_price=price,
                    peak_price=price,
                    entry_time=datetime.now(timezone.utc),
                    is_dry_run=False,
                )
            else:
                error = resp.get("errorMsg", "Unknown error")
                trade.status = OrderStatus.REJECTED
                trade.notes = f"REJECTED: {error}"
                logger.warning(f"❌ Order rejected: {error}")

            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data)
            return trade

        except Exception as e:
            trade.status = OrderStatus.REJECTED
            trade.notes = f"ERROR: {str(e)}"
            logger.error(f"❌ Order error: {e}")
            trade.id = db.insert_trade(trade, trade_log_data=trade_log_data)
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
                
                # Update trade log data
                updated_log_data = json.dumps(log_entry, default=str)
                db.update_trade(trade.id, pnl=pnl, status="filled", trade_log_data=updated_log_data)

        # Close position
        del self._open_positions[condition_id]
        return pnl

    def update_position_prices(self, condition_id: str):
        """Update current price and peak price for an open position."""
        position = self._open_positions.get(condition_id)
        if not position:
            return

        try:
            current_price = polymarket_client.get_midpoint(position.token_id)
            position.current_price = current_price
            position.unrealized_pnl = (current_price - position.entry_price) * position.size

            # Track high-water mark for trailing stop
            if current_price > position.peak_price:
                position.peak_price = current_price
        except Exception as e:
            logger.debug(f"Could not update position price: {e}")

    def cancel_all(self):
        """Cancel all open orders (live mode only)."""
        if polymarket_client.is_authenticated:
            try:
                polymarket_client.cancel_all_orders()
                logger.info("All open orders cancelled")
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")


# Global singleton
order_manager = OrderManager()
