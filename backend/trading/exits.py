"""
Exit Strategy Monitor.

Checks open positions against stop-loss conditions each tick:
1. Trailing stop — sell if price drops X% from peak
2. Time-decay tightening — tighter stops as window closes
3. BTC pressure scaling — short-term TA widens/tightens stops dynamically
4. Signal reversal — exit if signals flip hard against position
5. Hard floor — absolute max loss per trade

The key insight: the TOKEN price lags BTC reality. If 1m/5m/15m EMAs
are moving hard against your position, the token hasn't caught up yet.
Tighten the stop BEFORE the token dumps. Conversely, if short-term BTC
is ripping in your favor, give the position room to breathe.

Called from the trading engine's main loop.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from config import config_manager
from models import CompositeSignal, Side, Position, MarketInfo
from polymarket.orders import order_manager
from polymarket.markets import market_discovery
from binance.client import binance_client
from signals.btc_ta import compute_short_term_pressure

logger = logging.getLogger(__name__)


def _compute_pressure_multiplier(
    position_side: Side,
    pressure: dict,
) -> float:
    """
    Convert BTC short-term pressure into a stop-loss multiplier.
    
    Args:
        position_side: Which side we're holding (UP or DOWN)
        pressure: Output from compute_short_term_pressure()
    
    Returns:
        Multiplier for the trailing stop percentage:
        - > 1.0: BTC supports our position -> widen stop (more room)
        - 1.0: neutral
        - < 1.0: BTC is against us -> tighten stop (less tolerance)
    """
    exit_config = config_manager.config.exit
    raw_pressure = pressure.get("pressure", 0.0)

    if not exit_config.pressure_scaling_enabled:
        return 1.0

    # Determine if pressure is WITH or AGAINST our position
    # Holding UP: positive pressure = with us, negative = against
    # Holding DOWN: negative pressure = with us, positive = against
    if position_side == Side.UP:
        aligned_pressure = raw_pressure   # positive = good for UP
    else:
        aligned_pressure = -raw_pressure  # negative BTC pressure = good for DOWN

    # Dead zone -- small pressure means no adjustment
    if abs(aligned_pressure) < exit_config.pressure_neutral_zone:
        return 1.0

    # Scale linearly from neutral zone to extremes
    if aligned_pressure > 0:
        # BTC supports our position -> widen the stop
        t = (aligned_pressure - exit_config.pressure_neutral_zone) / (1.0 - exit_config.pressure_neutral_zone)
        t = min(t, 1.0)
        multiplier = 1.0 + t * (exit_config.pressure_widen_max - 1.0)
    else:
        # BTC is against our position -> tighten the stop
        t = (abs(aligned_pressure) - exit_config.pressure_neutral_zone) / (1.0 - exit_config.pressure_neutral_zone)
        t = min(t, 1.0)
        multiplier = 1.0 - t * (1.0 - exit_config.pressure_tighten_min)

    return round(multiplier, 3)


def check_exit_conditions(
    market: MarketInfo,
    signal: CompositeSignal,
) -> Optional[tuple[str, float]]:
    """
    Check if any open position should be exited early.
    
    Args:
        market: Current active market
        signal: Latest composite signal
        
    Returns:
        (reason, pnl) if a position was closed, None otherwise
    """
    exit_config = config_manager.config.exit

    if not exit_config.enabled:
        return None

    position = order_manager._open_positions.get(market.condition_id)
    if not position:
        return None

    # Update prices first (also tracks peak)
    order_manager.update_position_prices(market.condition_id)

    now = datetime.now(timezone.utc)

    # --- Check minimum hold time ---
    if position.entry_time:
        held_seconds = (now - position.entry_time).total_seconds()
        if held_seconds < exit_config.min_hold_seconds:
            return None
    else:
        held_seconds = 999  # unknown entry time, don't block

    # --- Compute BTC short-term pressure ---
    try:
        candles = binance_client.fetch_all_timeframes()
        signal_config = config_manager.config.signal
        pressure = compute_short_term_pressure(candles, signal_config)
    except Exception as e:
        logger.debug(f"Could not compute BTC pressure: {e}")
        pressure = {"pressure": 0.0, "momentum": 0.0, "alignment": 0, "details": {}}

    pressure_multiplier = _compute_pressure_multiplier(position.side, pressure)

    # --- Determine base trailing stop from time remaining ---
    time_remaining = market_discovery.time_until_close()
    base_trailing = exit_config.trailing_stop_pct

    time_zone_label = "normal"
    if time_remaining is not None:
        if time_remaining <= exit_config.final_seconds:
            base_trailing = exit_config.final_trailing_pct
            time_zone_label = "FINAL"
        elif time_remaining <= exit_config.tighten_at_seconds:
            base_trailing = exit_config.tightened_trailing_pct
            time_zone_label = "TIGHT"

    # --- Apply pressure multiplier to trailing stop ---
    effective_trailing = base_trailing * pressure_multiplier

    # Clamp: never wider than 40%, never tighter than 2%
    effective_trailing = max(0.02, min(0.40, effective_trailing))

    # --- Log the exit check state when interesting ---
    if position.current_price > 0 and position.peak_price > 0:
        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price
        pressure_val = pressure.get("pressure", 0.0)
        momentum_val = pressure.get("momentum", 0.0)

        # Log when position is losing ground or BTC pressure is notable
        if drop_from_peak > 0.03 or abs(pressure_val) > 0.2:
            time_str = f"{time_remaining:.0f}s" if time_remaining is not None else "?"
            logger.info(
                f"📉 EXIT CHECK: {position.side.value.upper()} | "
                f"entry={position.entry_price:.3f} peak={position.peak_price:.3f} "
                f"now={position.current_price:.3f} (drop={drop_from_peak:.1%}) | "
                f"BTC pressure={pressure_val:+.2f} mom={momentum_val:+.2f} -> "
                f"multiplier={pressure_multiplier:.2f} | "
                f"stop={effective_trailing:.1%} ({time_zone_label}) | "
                f"time_left={time_str}"
            )

    # --- Check 1: Trailing stop (pressure-adjusted) ---
    if position.peak_price > 0 and position.current_price > 0:
        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price

        if drop_from_peak >= effective_trailing:
            reason = (
                f"trailing_stop: price {position.current_price:.3f} dropped "
                f"{drop_from_peak:.1%} from peak {position.peak_price:.3f} | "
                f"base_stop={base_trailing:.0%} x pressure={pressure_multiplier:.2f} "
                f"-> effective={effective_trailing:.1%} | "
                f"BTC pressure={pressure.get('pressure', 0):+.2f} [{time_zone_label}]"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            is_dry = config_manager.config.mode != "live"
            pnl = order_manager.sell_position(market.condition_id, reason=reason, is_dry_run=is_dry)
            if pnl is not None:
                return reason, pnl

    # --- Check 2: Hard floor stop (NOT pressure-adjusted -- absolute safety net) ---
    if position.current_price > 0 and position.entry_price > 0:
        drop_from_entry = (position.entry_price - position.current_price) / position.entry_price

        if drop_from_entry >= exit_config.hard_stop_pct:
            reason = (
                f"hard_stop: price {position.current_price:.3f} dropped "
                f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                f"(hard limit: {exit_config.hard_stop_pct:.0%})"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            is_dry = config_manager.config.mode != "live"
            pnl = order_manager.sell_position(market.condition_id, reason=reason, is_dry_run=is_dry)
            if pnl is not None:
                return reason, pnl

    # --- Check 3: Signal reversal ---
    if signal and signal.recommended_side is not None:
        position_is_up = position.side == Side.UP
        signal_is_against = (
            (position_is_up and signal.composite_score < -exit_config.signal_reversal_threshold)
            or
            (not position_is_up and signal.composite_score > exit_config.signal_reversal_threshold)
        )

        if signal_is_against:
            reason = (
                f"signal_reversal: holding {position.side.value.upper()} but "
                f"signal={signal.composite_score:+.3f} | "
                f"BTC pressure={pressure.get('pressure', 0):+.2f} "
                f"(reversal threshold: +/-{exit_config.signal_reversal_threshold})"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            is_dry = config_manager.config.mode != "live"
            pnl = order_manager.sell_position(market.condition_id, reason=reason, is_dry_run=is_dry)
            if pnl is not None:
                return reason, pnl

    return None
