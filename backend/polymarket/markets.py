"""
Market discovery and rotation for Polymarket BTC 15-min markets.

These markets follow a pattern:
- New market opens every 15 minutes
- Question like "BTC 15 Minute Up or Down"
- Two outcomes: "Up" and "Down"
- Resolves based on BTC price at close vs open of the window

Uses the Gamma API to discover active markets and extract token IDs.

ASYNC version with:
- Async HTTP client
- Parallel window slug queries
- Market caching to reduce API calls
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import POLYMARKET_GAMMA_HOST
from models import MarketInfo

logger = logging.getLogger(__name__)

BTC_15M_SLUG_PATTERN = "btc-updown-15m"
WINDOW_DURATION_SECONDS = 900
MARKET_CACHE_TTL = 30.0


class MarketDiscovery:
    """Discovers and tracks active Polymarket BTC 15-min markets."""

    def __init__(self):
        self._current_market: Optional[MarketInfo] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._last_scan: float = 0.0
        self._market_cache_time: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def current_market(self) -> Optional[MarketInfo]:
        return self._current_market

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self):
        """Close the HTTP client connection."""
        if self._http:
            await self._http.aclose()
            self._http = None

    async def scan_for_active_market(self) -> Optional[MarketInfo]:
        """
        Query the Gamma API for the current active BTC 15-min market.
        Uses caching to reduce API calls.
        Returns MarketInfo if found, None otherwise.
        """
        now = time.time()
        
        async with self._lock:
            if (
                self._current_market 
                and (now - self._market_cache_time) < MARKET_CACHE_TTL
                and not self.should_stop_trading(buffer_seconds=60)
            ):
                return self._current_market

        try:
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
                async with self._lock:
                    self._current_market = market
                    self._market_cache_time = now
                return market

            logger.warning("No active BTC 15-min market found")
            return None

        except Exception as e:
            logger.error(f"Error scanning for markets: {e}")
            return None

    async def _find_btc_15m_market(self) -> Optional[MarketInfo]:
        """
        Search Gamma API for the current BTC 15-minute prediction market.
        
        Queries current, previous, and next windows in PARALLEL instead of
        sequentially, reducing discovery time from ~900ms to ~300ms.
        """
        try:
            current_ts = self.get_current_window_timestamp()
            
            slugs_and_ts = [
                (self.get_window_slug(current_ts), current_ts),
                (self.get_window_slug(current_ts - WINDOW_DURATION_SECONDS), current_ts - WINDOW_DURATION_SECONDS),
                (self.get_window_slug(current_ts + WINDOW_DURATION_SECONDS), current_ts + WINDOW_DURATION_SECONDS),
            ]

            client = await self._get_client()
            
            tasks = [
                client.get(
                    f"{POLYMARKET_GAMMA_HOST}/events",
                    params={"slug": slug},
                )
                for slug, _ in slugs_and_ts
            ]

            logger.info(f"Parallel querying {len(tasks)} window slugs")
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            for i, resp in enumerate(responses):
                if isinstance(resp, Exception):
                    logger.debug(f"Query {i} failed: {resp}")
                    continue
                
                try:
                    resp.raise_for_status()
                    events = resp.json()
                    
                    if events:
                        event = events[0]
                        slug, ts = slugs_and_ts[i]
                        
                        if i == 0:
                            logger.info(f"Found current window market: {event.get('title')}")
                        else:
                            if event.get("active") and not event.get("closed"):
                                markets = event.get("markets", [])
                                if markets:
                                    logger.info(f"Found adjacent window market: {event.get('title')}")
                                    return self._parse_event_to_market_info(event, markets)
                            continue
                        
                        markets = event.get("markets", [])
                        if markets:
                            return self._parse_event_to_market_info(event, markets)
                except Exception as e:
                    logger.debug(f"Error parsing response {i}: {e}")
                    continue

            logger.warning("No active BTC 15-min market found in any window")
            return None

        except httpx.HTTPError as e:
            logger.error(f"HTTP error searching markets: {e}")
            return None

    def _parse_event_to_market_info(self, event: dict, markets: list) -> Optional[MarketInfo]:
        """
        Parse a Gamma API event response into our MarketInfo model.
        """
        up_token = None
        down_token = None
        condition_id = None
        question = event.get("title", "")
        end_time = None

        for market in markets:
            condition_id = market.get("conditionId") or market.get("condition_id")
            question = market.get("question", question)

            end_str = market.get("endDate") or market.get("end_date_iso")
            if end_str:
                try:
                    end_time = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            clob_token_ids = market.get("clobTokenIds")
            outcomes = market.get("outcomes")

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
            return False
        return remaining < buffer_seconds

    @staticmethod
    def get_current_window_timestamp() -> int:
        """
        Calculate the Unix timestamp for the current 15-minute trading window.
        """
        now = int(time.time())
        return (now // WINDOW_DURATION_SECONDS) * WINDOW_DURATION_SECONDS

    @staticmethod
    def get_next_window_timestamp() -> int:
        """Calculate the Unix timestamp for the next 15-minute trading window."""
        current = MarketDiscovery.get_current_window_timestamp()
        return current + WINDOW_DURATION_SECONDS

    @staticmethod
    def get_window_slug(timestamp: int) -> str:
        """Generate the Polymarket event slug for a given window timestamp."""
        return f"{BTC_15M_SLUG_PATTERN}-{timestamp}"

    @staticmethod
    def get_window_url(timestamp: int) -> str:
        """Generate the full Polymarket URL for a given window timestamp."""
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


market_discovery = MarketDiscovery()