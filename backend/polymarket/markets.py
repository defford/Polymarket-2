"""
Market discovery and rotation for Polymarket BTC 15-min markets.

These markets follow a pattern:
- New market opens every 15 minutes
- Question like "BTC 15 Minute Up or Down"
- Two outcomes: "Up" and "Down"
- Resolves based on BTC price at close vs open of the window

Uses the Gamma API to discover active markets and extract token IDs.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import POLYMARKET_GAMMA_HOST
from models import MarketInfo

logger = logging.getLogger(__name__)

# BTC 15-min market slug pattern (e.g., btc-updown-15m-1770340500)
BTC_15M_SLUG_PATTERN = "btc-updown-15m"

# Market window duration in seconds
WINDOW_DURATION_SECONDS = 900  # 15 minutes


class MarketDiscovery:
    """Discovers and tracks active Polymarket BTC 15-min markets."""

    def __init__(self):
        self._current_market: Optional[MarketInfo] = None
        self._http = httpx.Client(timeout=15.0)
        self._last_scan = 0.0

    @property
    def current_market(self) -> Optional[MarketInfo]:
        return self._current_market

    async def scan_for_active_market(self) -> Optional[MarketInfo]:
        """
        Query the Gamma API for the current active BTC 15-min market.
        Returns MarketInfo if found, None otherwise.
        """
        try:
            # Search for active BTC 15-minute events
            market = await self._find_btc_15m_market()
            if market:
                if (
                    self._current_market is None
                    or self._current_market.condition_id != market.condition_id
                ):
                    logger.info(
                        f"New active market found: {market.question} "
                        f"(condition={market.condition_id[:16]}...)"
                    )
                self._current_market = market
                return market

            logger.warning("No active BTC 15-min market found")
            return None

        except Exception as e:
            logger.error(f"Error scanning for markets: {e}")
            return None

    async def _find_btc_15m_market(self) -> Optional[MarketInfo]:
        """
        Search Gamma API for the current BTC 15-minute prediction market.
        
        The 15-min markets are NOT included in general API listings.
        We must query with the exact slug, calculated from the current timestamp.
        """
        try:
            # Strategy 1: Query by calculated slug (most reliable for 15-min markets)
            # These markets aren't in general listings, must query by exact slug
            current_ts = self.get_current_window_timestamp()
            current_slug = self.get_window_slug(current_ts)
            
            logger.info(f"Searching for current window market: {current_slug}")
            
            resp = self._http.get(
                f"{POLYMARKET_GAMMA_HOST}/events",
                params={"slug": current_slug},
            )
            resp.raise_for_status()
            events = resp.json()
            
            if events:
                event = events[0]
                markets = event.get("markets", [])
                if markets:
                    logger.info(f"Found current window market: {event.get('title')}")
                    return self._parse_event_to_market_info(event, markets)
            
            # Strategy 2: Try previous window (might still be active near boundaries)
            prev_ts = current_ts - WINDOW_DURATION_SECONDS
            prev_slug = self.get_window_slug(prev_ts)
            
            logger.debug(f"Current window not found, trying previous: {prev_slug}")
            
            resp = self._http.get(
                f"{POLYMARKET_GAMMA_HOST}/events",
                params={"slug": prev_slug},
            )
            resp.raise_for_status()
            events = resp.json()
            
            if events:
                event = events[0]
                # Only use if still active
                if event.get("active") and not event.get("closed"):
                    markets = event.get("markets", [])
                    if markets:
                        logger.info(f"Using previous window market: {event.get('title')}")
                        return self._parse_event_to_market_info(event, markets)
            
            # Strategy 3: Try next window (markets may be created early)
            next_ts = current_ts + WINDOW_DURATION_SECONDS
            next_slug = self.get_window_slug(next_ts)
            
            logger.debug(f"Trying next window: {next_slug}")
            
            resp = self._http.get(
                f"{POLYMARKET_GAMMA_HOST}/events",
                params={"slug": next_slug},
            )
            resp.raise_for_status()
            events = resp.json()
            
            if events:
                event = events[0]
                if event.get("active") and not event.get("closed"):
                    markets = event.get("markets", [])
                    if markets:
                        logger.info(f"Using next window market: {event.get('title')}")
                        return self._parse_event_to_market_info(event, markets)

            logger.warning(f"No active BTC 15-min market found for windows: {current_slug}, {prev_slug}, {next_slug}")
            return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error searching markets: {e}")
            return None

    def _parse_event_to_market_info(self, event: dict, markets: list) -> Optional[MarketInfo]:
        """
        Parse a Gamma API event response into our MarketInfo model.
        
        BTC 15-min events typically have a single market with 2 outcomes (Up/Down).
        Each outcome has a distinct token_id (clobTokenId).
        """
        # The event may contain multiple market objects, 
        # but for Up/Down it's typically one market with two tokens
        up_token = None
        down_token = None
        condition_id = None
        question = event.get("title", "")
        end_time = None

        for market in markets:
            condition_id = market.get("conditionId") or market.get("condition_id")
            question = market.get("question", question)

            # Parse end date
            end_str = market.get("endDate") or market.get("end_date_iso")
            if end_str:
                try:
                    end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # Get token IDs from clobTokenIds or outcomes
            # Note: Gamma API returns these as JSON strings, not lists
            clob_token_ids = market.get("clobTokenIds")
            outcomes = market.get("outcomes")

            # Parse JSON strings if needed
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = None
            
            if isinstance(outcomes, str):
                try:
                    outcomes = json.loads(outcomes)
                except (json.JSONDecodeError, TypeError):
                    outcomes = None

            if clob_token_ids and outcomes:
                for i, outcome in enumerate(outcomes):
                    token_id = clob_token_ids[i] if i < len(clob_token_ids) else None
                    if token_id:
                        outcome_lower = outcome.lower()
                        if outcome_lower in ("up", "yes"):
                            up_token = token_id
                        elif outcome_lower in ("down", "no"):
                            down_token = token_id

            # Also try tokens array format
            tokens = market.get("tokens", [])
            for token in tokens:
                token_id = token.get("token_id") or token.get("tokenId")
                outcome = (token.get("outcome") or "").lower()
                if token_id:
                    if outcome in ("up", "yes"):
                        up_token = token_id
                    elif outcome in ("down", "no"):
                        down_token = token_id

        if condition_id and up_token and down_token:
            return MarketInfo(
                condition_id=condition_id,
                question=question,
                up_token_id=up_token,
                down_token_id=down_token,
                end_time=end_time,
                market_slug=event.get("slug"),
                active=True,
            )

        logger.warning(f"Could not parse market tokens from event: {question}")
        return None

    def _parse_single_market(self, market: dict) -> Optional[MarketInfo]:
        """Parse a single market object from Gamma API."""
        condition_id = market.get("conditionId") or market.get("condition_id")
        question = market.get("question", "")
        up_token = None
        down_token = None

        clob_token_ids = market.get("clobTokenIds", [])
        outcomes = market.get("outcomes", [])

        # Parse JSON strings if needed (Gamma API returns these as strings)
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = []
        
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except (json.JSONDecodeError, TypeError):
                outcomes = []

        if clob_token_ids and outcomes:
            for i, outcome in enumerate(outcomes):
                if i < len(clob_token_ids):
                    outcome_lower = outcome.lower()
                    if outcome_lower in ("up", "yes"):
                        up_token = clob_token_ids[i]
                    elif outcome_lower in ("down", "no"):
                        down_token = clob_token_ids[i]

        tokens = market.get("tokens", [])
        for token in tokens:
            token_id = token.get("token_id") or token.get("tokenId")
            outcome = (token.get("outcome") or "").lower()
            if token_id:
                if outcome in ("up", "yes"):
                    up_token = token_id
                elif outcome in ("down", "no"):
                    down_token = token_id

        end_str = market.get("endDate") or market.get("end_date_iso")
        end_time = None
        if end_str:
            try:
                end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        if condition_id and up_token and down_token:
            return MarketInfo(
                condition_id=condition_id,
                question=question,
                up_token_id=up_token,
                down_token_id=down_token,
                end_time=end_time,
                market_slug=market.get("slug"),
                active=True,
            )

        return None

    def time_until_close(self) -> Optional[float]:
        """Seconds until the current market closes. None if unknown."""
        if not self._current_market or not self._current_market.end_time:
            return None
        now = datetime.now(timezone.utc)
        end = self._current_market.end_time
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = (end - now).total_seconds()
        return max(0, delta)

    def should_stop_trading(self, buffer_seconds: int = 120) -> bool:
        """Check if we're too close to market close."""
        remaining = self.time_until_close()
        if remaining is None:
            return False  # Unknown, keep trading
        return remaining < buffer_seconds

    @staticmethod
    def get_current_window_timestamp() -> int:
        """
        Calculate the Unix timestamp for the current 15-minute trading window.
        
        Windows align to :00, :15, :30, :45 of each hour.
        Returns the timestamp of the current window's start.
        """
        now = int(time.time())
        # Round down to nearest 15-minute boundary
        return (now // WINDOW_DURATION_SECONDS) * WINDOW_DURATION_SECONDS

    @staticmethod
    def get_next_window_timestamp() -> int:
        """
        Calculate the Unix timestamp for the next 15-minute trading window.
        """
        current = MarketDiscovery.get_current_window_timestamp()
        return current + WINDOW_DURATION_SECONDS

    @staticmethod
    def get_window_slug(timestamp: int) -> str:
        """
        Generate the Polymarket event slug for a given window timestamp.
        
        Example: btc-updown-15m-1770340500
        """
        return f"{BTC_15M_SLUG_PATTERN}-{timestamp}"

    @staticmethod
    def get_window_url(timestamp: int) -> str:
        """
        Generate the full Polymarket URL for a given window timestamp.
        
        Example: https://polymarket.com/event/btc-updown-15m-1770340500
        """
        slug = MarketDiscovery.get_window_slug(timestamp)
        return f"https://polymarket.com/event/{slug}"

    def get_current_window_info(self) -> dict:
        """Get info about current and next trading windows."""
        current_ts = self.get_current_window_timestamp()
        next_ts = self.get_next_window_timestamp()
        now = int(time.time())
        
        return {
            "current_window": {
                "timestamp": current_ts,
                "slug": self.get_window_slug(current_ts),
                "url": self.get_window_url(current_ts),
                "seconds_remaining": current_ts + WINDOW_DURATION_SECONDS - now,
            },
            "next_window": {
                "timestamp": next_ts,
                "slug": self.get_window_slug(next_ts),
                "url": self.get_window_url(next_ts),
                "starts_in_seconds": next_ts - now,
            },
        }


# Global singleton
market_discovery = MarketDiscovery()
