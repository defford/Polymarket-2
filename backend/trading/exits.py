"""
Exit Strategy Evaluator.

Evaluates open positions against stop-loss conditions each tick and returns
exit decisions. Does NOT execute sells — the engine handles that.

Checks:
1. Survival Buffer — 15 BPS hard stop for first 180s, no trailing
2. Trailing stop — sell if price drops X% from peak (only after buffer, if profitable)
3. Time-decay tightening — tighter stops as window closes
4. BTC pressure scaling — short-term TA widens/tightens stops dynamically
5. Signal reversal — exit if signals flip hard against position
6. Hard floor — absolute max loss per trade
7. Conviction scaling — adjust TP/trail based on entry conviction

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
from polymarket.markets import market_discovery
from binance.client import binance_client
from signals.btc_ta import compute_short_term_pressure

logger = logging.getLogger(__name__)


def _compute_pressure_multiplier(
    position_side: Side,
    pressure: dict,
    config_mgr=None,
) -> float:
    """
    Convert BTC short-term pressure into a stop-loss multiplier.

    Args:
        position_side: Which side we're holding (UP or DOWN)
        pressure: Output from compute_short_term_pressure()
        config_mgr: Optional config manager (default: global)

    Returns:
        Multiplier for the trailing stop percentage:
        - > 1.0: BTC supports our position -> widen stop (more room)
        - 1.0: neutral
        - < 1.0: BTC is against us -> tighten stop (less tolerance)
    """
    _cfg = config_mgr if config_mgr is not None else config_manager
    exit_config = _cfg.config.exit
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


def evaluate_exit(
    position: Position,
    signal: CompositeSignal,
    config_mgr=None,
    mkt_discovery=None,
    btc_client=None,
) -> Optional[dict]:
    """
    Evaluate whether an open position should be exited early.

    Returns a decision dict if exit is warranted, None otherwise.
    The engine is responsible for executing the sell.

    Args:
        position: The open position to evaluate
        signal: Latest composite signal
        config_mgr: Optional config manager (default: global)
        mkt_discovery: Optional market discovery (default: global)
        btc_client: Optional binance client (default: global)

    Returns:
        Decision dict with keys:
            reason: Full human-readable reason string
            reason_category: "trailing_stop" | "hard_take_profit" | "hard_stop" | "signal_reversal"
            effective_trailing_pct: The final trailing stop % used
            pressure_multiplier: BTC pressure multiplier applied
            time_zone: "normal" | "TIGHT" | "FINAL" | "SURVIVAL"
            btc_pressure: Raw BTC pressure value
            conviction_tier: "high" | "normal" | "low"
        Or None if no exit warranted.
    """
    _cfg = config_mgr if config_mgr is not None else config_manager
    _discovery = mkt_discovery if mkt_discovery is not None else market_discovery
    _btc = btc_client if btc_client is not None else binance_client

    exit_config = _cfg.config.exit

    if not exit_config.enabled:
        return None

    now = datetime.now(timezone.utc)

    if position.entry_time:
        held_seconds = (now - position.entry_time).total_seconds()
        if held_seconds < exit_config.min_hold_seconds:
            return None
    else:
        held_seconds = 999

    in_survival_buffer = (
        exit_config.survival_buffer_enabled
        and held_seconds < exit_config.survival_buffer_seconds
    )

    conviction = position.entry_conviction if position.entry_conviction > 0 else 0.5
    if conviction >= exit_config.high_conviction_threshold:
        conviction_tier = "high"
    elif conviction <= exit_config.low_conviction_threshold:
        conviction_tier = "low"
    else:
        conviction_tier = "normal"

    is_profitable = position.current_price > position.entry_price

    try:
        candles = _btc.fetch_all_timeframes()
        signal_config = _cfg.config.signal
        pressure = compute_short_term_pressure(candles, signal_config)
    except Exception as e:
        logger.debug(f"Could not compute BTC pressure: {e}")
        pressure = {"pressure": 0.0, "momentum": 0.0, "alignment": 0, "details": {}}

    pressure_multiplier = _compute_pressure_multiplier(position.side, pressure, config_mgr=_cfg)

    time_remaining = _discovery.time_until_close()
    base_trailing = exit_config.trailing_stop_pct
    effective_tp = exit_config.hard_tp_pct

    time_zone_label = "normal"
    if in_survival_buffer:
        time_zone_label = "SURVIVAL"
        base_trailing = 1.0
    elif time_remaining is not None:
        if time_remaining <= exit_config.final_seconds:
            base_trailing = exit_config.final_trailing_pct
            time_zone_label = "FINAL"
        elif time_remaining <= exit_config.tighten_at_seconds:
            base_trailing = exit_config.tightened_trailing_pct
            time_zone_label = "TIGHT"

    if conviction_tier == "high":
        effective_tp = exit_config.high_conviction_tp_pct
    elif conviction_tier == "low":
        base_trailing = min(base_trailing, exit_config.low_conviction_trail_pct)

    effective_trailing = base_trailing * pressure_multiplier

    if exit_config.scaling_tp_enabled and position.entry_price > 0 and is_profitable:
        gain_pct = (position.current_price - position.entry_price) / position.entry_price
        stop_reduction = exit_config.scaling_tp_pct * gain_pct
        effective_trailing = effective_trailing * (1.0 - stop_reduction)
        effective_trailing = max(effective_trailing, exit_config.scaling_tp_min_trail)

    pressure_val = pressure.get("pressure", 0.0)
    momentum_val = pressure.get("momentum", 0.0)

    if position.current_price > 0 and position.peak_price > 0:
        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price

        if drop_from_peak > 0.03 or abs(pressure_val) > 0.2 or in_survival_buffer:
            time_str = f"{time_remaining:.0f}s" if time_remaining is not None else "?"
            logger.info(
                f"📉 EXIT CHECK: {position.side.value.upper()} | "
                f"entry={position.entry_price:.3f} peak={position.peak_price:.3f} "
                f"now={position.current_price:.3f} (drop={drop_from_peak:.1%}) | "
                f"conviction={conviction:.2f} ({conviction_tier}) | "
                f"BTC pressure={pressure_val:+.2f} -> multiplier={pressure_multiplier:.2f} | "
                f"stop={effective_trailing:.1%} TP={effective_tp:.1%} ({time_zone_label}) | "
                f"held={held_seconds:.0f}s left={time_str}"
            )

    base_decision = {
        "effective_trailing_pct": effective_trailing,
        "pressure_multiplier": pressure_multiplier,
        "time_zone": time_zone_label,
        "btc_pressure": pressure_val,
        "conviction_tier": conviction_tier,
    }

    if in_survival_buffer:
        if position.current_price > 0 and position.entry_price > 0:
            survival_hard_stop = exit_config.survival_hard_stop_bps / 10000.0
            drop_from_entry = (position.entry_price - position.current_price) / position.entry_price

            if drop_from_entry >= survival_hard_stop:
                reason = (
                    f"survival_hard_stop: price {position.current_price:.3f} dropped "
                    f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                    f"(survival buffer: {survival_hard_stop:.2%} for {held_seconds:.0f}s)"
                )
                logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
                return {**base_decision, "reason": reason, "reason_category": "hard_stop"}
        return None

    if not is_profitable:
        if position.current_price > 0 and position.entry_price > 0:
            drop_from_entry = (position.entry_price - position.current_price) / position.entry_price

            if drop_from_entry >= exit_config.hard_stop_pct:
                reason = (
                    f"hard_stop: price {position.current_price:.3f} dropped "
                    f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                    f"(hard limit: {exit_config.hard_stop_pct:.0%})"
                )
                logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
                return {**base_decision, "reason": reason, "reason_category": "hard_stop"}

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
                    f"signal={signal.composite_score:+.3f} (underwater, no trailing)"
                )
                logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
                return {**base_decision, "reason": reason, "reason_category": "signal_reversal"}

        return None

    if conviction_tier == "low":
        tick = 0.01
        target_price = position.current_price + tick
        if position.current_price >= target_price - tick:
            reason = (
                f"low_conviction_take_profit: conviction={conviction:.2f} < {exit_config.low_conviction_threshold:.2f} | "
                f"securing win at {position.current_price:.3f}"
            )
            logger.info(f"🎯 EXIT TRIGGERED -- {reason}")
            return {**base_decision, "reason": reason, "reason_category": "hard_take_profit"}

    if position.peak_price > 0 and position.current_price > 0:
        drop_from_peak = (position.peak_price - position.current_price) / position.peak_price

        if drop_from_peak >= effective_trailing:
            reason = (
                f"trailing_stop: price {position.current_price:.3f} dropped "
                f"{drop_from_peak:.1%} from peak {position.peak_price:.3f} | "
                f"effective={effective_trailing:.1%} [{time_zone_label}] | "
                f"conviction={conviction_tier}"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            return {**base_decision, "reason": reason, "reason_category": "trailing_stop"}

    if exit_config.hard_tp_enabled and position.entry_price > 0 and position.current_price > 0:
        gain_from_entry = (position.current_price - position.entry_price) / position.entry_price
        if gain_from_entry >= effective_tp:
            reason = (
                f"hard_take_profit: price {position.current_price:.3f} rose "
                f"{gain_from_entry:.1%} from entry {position.entry_price:.3f} "
                f"(TP limit: {effective_tp:.0%}, conviction={conviction_tier}) | "
                f"BTC pressure={pressure_val:+.2f}"
            )
            logger.info(f"🎯 EXIT TRIGGERED -- {reason}")
            return {**base_decision, "reason": reason, "reason_category": "hard_take_profit"}

    if position.current_price > 0 and position.entry_price > 0:
        drop_from_entry = (position.entry_price - position.current_price) / position.entry_price

        if drop_from_entry >= exit_config.hard_stop_pct:
            reason = (
                f"hard_stop: price {position.current_price:.3f} dropped "
                f"{drop_from_entry:.1%} from entry {position.entry_price:.3f} "
                f"(hard limit: {exit_config.hard_stop_pct:.0%})"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            return {**base_decision, "reason": reason, "reason_category": "hard_stop"}

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
                f"BTC pressure={pressure_val:+.2f} "
                f"(reversal threshold: +/-{exit_config.signal_reversal_threshold})"
            )
            logger.info(f"🛑 EXIT TRIGGERED -- {reason}")
            return {**base_decision, "reason": reason, "reason_category": "signal_reversal"}

    return None
