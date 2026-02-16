"""
Binance integration for BTC price candle data.
Fetches historical and live candles across multiple timeframes. 

Uses Binance public REST API (no API key needed for market data).
ASYNC version with parallel candle fetching for optimal performance.

Rate limited to prevent IP bans (418 errors).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd
import numpy as np

from config import BINANCE_SYMBOL
from binance.rate_limiter import binance_rate_limiter

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com"

TIMEFRAMES = {
    "1m": ("1m", 250),
    "5m": ("5m", 250),
    "15m": ("15m", 250),
    "1h": ("1h", 250),
    "4h": ("4h", 250),
    "1d": ("1d", 250),
}


class BinanceClient:
    """
    Fetches BTC/USDT candle data from Binance.
    Maintains a cache of candles per timeframe for TA calculations.
    
    Async implementation with:
    - Lazy AsyncClient initialization
    - Parallel candle fetching across timeframes
    - Thread-safe caching with asyncio.Lock
    - Rate limiting to prevent IP bans
    """
    
    # Shared orderbook cache to reduce API calls
    _orderbook_cache: dict = {}
    _orderbook_last_fetch: float = 0
    _orderbook_lock = asyncio.Lock()
    _orderbook_min_interval: float = 2.0

    def __init__(self):
        self._http: Optional[httpx.AsyncClient] = None
        self._candle_cache: dict[str, pd.DataFrame] = {}
        self._last_fetch: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._fetch_intervals = {
            "1m": 10,
            "5m": 30,
            "15m": 60,
            "1h": 120,
            "4h": 300,
            "1d": 600,
        }

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
    
    async def _make_request(
        self,
        endpoint: str,
        params: dict,
        max_retries: int = 3,
    ) -> tuple[Optional[dict], Optional[dict]]:
        """
        Make a rate-limited request to Binance API.
        
        Handles:
        - Pre-request rate limiting
        - 429/418 response handling with backoff
        - Response header tracking
        
        Returns (data, headers) tuple.
        """
        client = await self._get_client()
        url = f"{BINANCE_BASE_URL}{endpoint}"
        
        for attempt in range(max_retries):
            # Acquire rate limit permission
            wait_time = await binance_rate_limiter.acquire(endpoint, params)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            
            try:
                resp = await client.get(url, params=params)
                headers = dict(resp.headers)
                
                # Track rate limits from response
                await binance_rate_limiter.handle_response_headers(headers)
                
                # Handle rate limit responses
                if resp.status_code == 429:
                    retry_wait = await binance_rate_limiter.handle_429(headers)
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limited (429), waiting {retry_wait}s before retry")
                        await asyncio.sleep(retry_wait)
                        continue
                    return None, headers
                
                if resp.status_code == 418:
                    ban_wait = await binance_rate_limiter.handle_418(headers)
                    if attempt < max_retries - 1:
                        logger.error(f"IP banned (418), waiting {ban_wait}s")
                        await asyncio.sleep(ban_wait)
                        continue
                    return None, headers
                
                resp.raise_for_status()
                
                # Record successful request
                await binance_rate_limiter.record_request(endpoint, params)
                await binance_rate_limiter.record_success()
                
                return resp.json(), headers
                
            except httpx.HTTPStatusError as e:
                logger.error(f"Binance HTTP error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None, {}
            except httpx.HTTPError as e:
                logger.error(f"Binance HTTP error fetching {endpoint}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None, {}
            except Exception as e:
                logger.error(f"Error fetching {endpoint}: {e}")
                return None, {}
        
        return None, {}

    async def fetch_candles(self, timeframe: str, limit: int = 250) -> Optional[pd.DataFrame]:
        """
        Fetch candles for a given timeframe.
        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        
        Uses caching with rate limiting to avoid hammering the API.
        """
        if timeframe not in TIMEFRAMES:
            logger.error(f"Unknown timeframe: {timeframe}")
            return None

        now = time.time()
        last = self._last_fetch.get(timeframe, 0)
        min_interval = self._fetch_intervals.get(timeframe, 10)

        async with self._lock:
            if now - last < min_interval and timeframe in self._candle_cache:
                return self._candle_cache[timeframe]

        binance_interval = TIMEFRAMES[timeframe][0]
        endpoint = "/api/v3/klines"
        params = {
            "symbol": BINANCE_SYMBOL,
            "interval": binance_interval,
            "limit": limit,
        }

        data, _ = await self._make_request(endpoint, params)
        
        if data is None:
            async with self._lock:
                return self._candle_cache.get(timeframe)

        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.sort_values("timestamp").reset_index(drop=True)

        async with self._lock:
            self._candle_cache[timeframe] = df
            self._last_fetch[timeframe] = now

        logger.debug(
            f"Fetched {len(df)} candles for {BINANCE_SYMBOL} {timeframe} "
            f"(latest: {df.iloc[-1]['close']:.2f})"
        )
        return df

    async def fetch_all_timeframes(self) -> dict[str, pd.DataFrame]:
        """
        Fetch candles for all configured timeframes with RATE LIMIT STAGGERING.
        
        Instead of parallel burst (which triggers bans), we stagger requests
        slightly while still being efficient.
        """
        results = {}
        
        for tf in TIMEFRAMES:
            df = await self.fetch_candles(tf)
            if df is not None and not df.empty:
                results[tf] = df
            # Small delay between timeframes to stay under rate limit
            await asyncio.sleep(0.15)
        
        return results

    async def get_current_price(self) -> Optional[float]:
        """Get the latest BTC price from the most recent 1m candle."""
        async with self._lock:
            df = self._candle_cache.get("1m")
        if df is not None and not df.empty:
            return float(df.iloc[-1]["close"])

        endpoint = "/api/v3/ticker/price"
        params = {"symbol": BINANCE_SYMBOL}
        
        data, _ = await self._make_request(endpoint, params)
        if data:
            return float(data.get("price", 0))
        return None

    async def get_orderbook(self, limit: int = 5) -> dict:
        """
        Get BTC orderbook for spread calculation.
        
        CACHED to reduce API calls - only fetches every 2 seconds max.
        Multiple concurrent calls share the same cached result.
        
        Returns dict with:
            - best_bid: float
            - best_ask: float
            - spread: float (absolute)
            - spread_bps: float (basis points)
            - mid_price: float
        """
        now = time.time()
        
        # Check cache first
        async with BinanceClient._orderbook_lock:
            if now - BinanceClient._orderbook_last_fetch < BinanceClient._orderbook_min_interval:
                if BinanceClient._orderbook_cache:
                    return BinanceClient._orderbook_cache
        
        endpoint = "/api/v3/depth"
        params = {
            "symbol": BINANCE_SYMBOL,
            "limit": limit,
        }
        
        data, _ = await self._make_request(endpoint, params)
        
        if data is None:
            async with BinanceClient._orderbook_lock:
                return BinanceClient._orderbook_cache or {
                    "best_bid": 0, "best_ask": 0, "spread": 0, 
                    "spread_bps": 0, "mid_price": 0
                }
        
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        if not bids or not asks:
            return {"best_bid": 0, "best_ask": 0, "spread": 0, "spread_bps": 0, "mid_price": 0}
        
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2
        spread_bps = (spread / mid_price * 10000) if mid_price > 0 else 0
        
        result = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "spread_bps": spread_bps,
            "mid_price": mid_price,
        }
        
        async with BinanceClient._orderbook_lock:
            BinanceClient._orderbook_cache = result
            BinanceClient._orderbook_last_fetch = now
        
        return result

    def get_cached_candles(self, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached candles without fetching (sync accessor for backward compat)."""
        return self._candle_cache.get(timeframe)
    
    def get_rate_limit_state(self) -> dict:
        """Get current rate limiter state for monitoring."""
        return binance_rate_limiter.get_state()


binance_client = BinanceClient()