"""
Binance integration for BTC price candle data.
Fetches historical and live candles across multiple timeframes.

Uses Binance public REST API (no API key needed for market data).
ASYNC version with parallel candle fetching for optimal performance.
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
    """

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

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{BINANCE_BASE_URL}/api/v3/klines",
                params={
                    "symbol": BINANCE_SYMBOL,
                    "interval": binance_interval,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()

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

        except httpx.HTTPError as e:
            logger.error(f"Binance HTTP error fetching {timeframe} candles: {e}")
            async with self._lock:
                return self._candle_cache.get(timeframe)
        except Exception as e:
            logger.error(f"Error fetching {timeframe} candles: {e}")
            async with self._lock:
                return self._candle_cache.get(timeframe)

    async def fetch_all_timeframes(self) -> dict[str, pd.DataFrame]:
        """
        Fetch candles for all configured timeframes in PARALLEL.
        
        This is the key optimization - instead of sequential fetching
        which takes 6 * ~200ms = ~1200ms, we fetch all 6 in parallel
        taking only ~200-300ms total.
        """
        tasks = [self.fetch_candles(tf) for tf in TIMEFRAMES]
        results = await asyncio.gather(*tasks)
        
        result = {}
        for tf, df in zip(TIMEFRAMES.keys(), results):
            if df is not None and not df.empty:
                result[tf] = df
        return result

    async def get_current_price(self) -> Optional[float]:
        """Get the latest BTC price from the most recent 1m candle."""
        async with self._lock:
            df = self._candle_cache.get("1m")
        if df is not None and not df.empty:
            return float(df.iloc[-1]["close"])

        try:
            client = await self._get_client()
            resp = await client.get(
                f"{BINANCE_BASE_URL}/api/v3/ticker/price",
                params={"symbol": BINANCE_SYMBOL},
            )
            resp.raise_for_status()
            return float(resp.json()["price"])
        except Exception as e:
            logger.error(f"Error fetching current price: {e}")
            return None

    async def get_orderbook(self, limit: int = 5) -> dict:
        """
        Get BTC orderbook for spread calculation.
        
        Returns dict with:
            - best_bid: float
            - best_ask: float
            - spread: float (absolute)
            - spread_bps: float (basis points)
            - mid_price: float
        """
        try:
            client = await self._get_client()
            resp = await client.get(
                f"{BINANCE_BASE_URL}/api/v3/depth",
                params={
                    "symbol": BINANCE_SYMBOL,
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            
            if not bids or not asks:
                return {"best_bid": 0, "best_ask": 0, "spread": 0, "spread_bps": 0, "mid_price": 0}
            
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            spread_bps = (spread / mid_price * 10000) if mid_price > 0 else 0
            
            return {
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "spread_bps": spread_bps,
                "mid_price": mid_price,
            }
        except Exception as e:
            logger.error(f"Error fetching BTC orderbook: {e}")
            return {"best_bid": 0, "best_ask": 0, "spread": 0, "spread_bps": 0, "mid_price": 0}

    def get_cached_candles(self, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached candles without fetching (sync accessor for backward compat)."""
        return self._candle_cache.get(timeframe)


binance_client = BinanceClient()
