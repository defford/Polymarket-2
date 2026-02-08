"""
Risk management module.
Enforces trading limits, loss limits, and cooldown periods.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import config_manager
from models import CompositeSignal, OrderStatus


logger = logging.getLogger(__name__)


class RiskManager:
    """
    Enforces all risk management rules before allowing a trade.
    """

    def __init__(self):
        self._consecutive_losses = 0
        self._cooldown_until: Optional[datetime] = None
        self._trades_this_window: dict[str, int] = {}  # condition_id -> count
        self._daily_pnl = 0.0
        self._last_daily_reset: Optional[str] = None

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def is_in_cooldown(self) -> bool:
        if self._cooldown_until is None:
            return False
        return datetime.now(timezone.utc) < self._cooldown_until

    @property
    def cooldown_remaining_seconds(self) -> float:
        if not self.is_in_cooldown:
            return 0.0
        delta = (self._cooldown_until - datetime.now(timezone.utc)).total_seconds()
        return max(0, delta)

    def can_trade(self, signal: CompositeSignal, market_condition_id: str) -> tuple[bool, str]:
        """
        Check if we're allowed to trade given current risk state.

        Returns:
            (allowed: bool, reason: str)
        """
        config = config_manager.config.risk

        # Reset daily stats if new day
        self._check_daily_reset()

        # Check cooldown
        if self.is_in_cooldown:
            remaining = self.cooldown_remaining_seconds
            return False, f"In cooldown ({remaining:.0f}s remaining)"

        # Check daily loss limit
        if self._daily_pnl <= -config.max_daily_loss:
            self._enter_cooldown(config.cooldown_minutes)
            return False, f"Daily loss limit hit (${self._daily_pnl:.2f} / -${config.max_daily_loss:.2f})"

        # Check consecutive losses
        if self._consecutive_losses >= config.max_consecutive_losses:
            self._enter_cooldown(config.cooldown_minutes)
            return False, (
                f"Max consecutive losses hit ({self._consecutive_losses} / "
                f"{config.max_consecutive_losses})"
            )

        # Check trades per window
        trades_in_window = self._trades_this_window.get(market_condition_id, 0)
        if trades_in_window >= config.max_trades_per_window:
            return False, (
                f"Max trades per window hit ({trades_in_window} / "
                f"{config.max_trades_per_window})"
            )

        # Check signal confidence
        if not signal.should_trade:
            return False, "Signal below threshold"

        return True, "OK"

    def get_position_size(self) -> float:
        """
        Get the allowed position size for the next trade.
        Could be reduced based on drawdown, consecutive losses, etc.
        """
        config = config_manager.config.risk
        base_size = config.max_position_size

        # Ensure we don't exceed daily loss limit
        remaining_budget = config.max_daily_loss + self._daily_pnl  # pnl is negative when losing
        if remaining_budget < base_size:
            base_size = max(0.0, remaining_budget)

        return round(base_size, 2)

    def record_trade_result(self, pnl: float, market_condition_id: str):
        """Record a trade result and update risk state."""
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
            logger.info(
                f"Loss recorded: ${pnl:.2f} | "
                f"Consecutive losses: {self._consecutive_losses} | "
                f"Daily P&L: ${self._daily_pnl:.2f}"
            )
        else:
            self._consecutive_losses = 0  # Reset on win
            logger.info(
                f"Win recorded: ${pnl:.2f} | "
                f"Daily P&L: ${self._daily_pnl:.2f}"
            )

        # Increment trades for this window
        self._trades_this_window[market_condition_id] = (
            self._trades_this_window.get(market_condition_id, 0) + 1
        )

    def on_market_change(self, new_condition_id: str):
        """Called when the active market rotates to a new 15-min window."""
        # Reset per-window counters (keep the new market's count at 0)
        self._trades_this_window = {}
        logger.debug(f"Market rotation: window trade counters reset")

    def reset_session_stats(self):
        """Reset session-specific stats (consecutive losses, etc)."""
        self._consecutive_losses = 0
        self._trades_this_window = {}
        # We don't necessarily reset daily_pnl here because that tracks the calendar day, 
        # but the request implies "stats start again from 0".
        # If the user wants the dashboard to start from 0 for the *session*, we should reset daily_pnl too
        # or separate session PnL from daily PnL.
        # The prompt says: "When I start again, a new session starts and the dashboard stats start again from 0."
        # This implies we should treat the "daily" stats on the dashboard as "current session" stats or reset them.
        self._daily_pnl = 0.0
        self._cooldown_until = None
        logger.info("Risk manager stats reset for new session")

    def _enter_cooldown(self, minutes: int):
        """Enter cooldown period."""
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        logger.warning(
            f"⏸️ Entering {minutes}-minute cooldown until "
            f"{self._cooldown_until.isoformat()}"
        )

    def _check_daily_reset(self):
        """Reset daily stats at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_daily_reset != today:
            if self._last_daily_reset is not None:
                logger.info(
                    f"📅 Daily reset: previous day P&L was ${self._daily_pnl:.2f}"
                )
            self._daily_pnl = 0.0
            self._consecutive_losses = 0
            self._cooldown_until = None
            self._trades_this_window = {}
            self._last_daily_reset = today

    def get_state(self) -> dict:
        """Get current risk state for the dashboard."""
        return {
            "consecutive_losses": self._consecutive_losses,
            "daily_pnl": self._daily_pnl,
            "is_in_cooldown": self.is_in_cooldown,
            "cooldown_remaining_seconds": self.cooldown_remaining_seconds,
            "next_position_size": self.get_position_size(),
        }


# Global singleton
risk_manager = RiskManager()
