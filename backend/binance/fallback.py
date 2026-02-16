"""
Fallback BTC price providers.

When Binance is blocked (418), these providers serve as backup sources
for BTC price data. Each provider implements a simple interface.

Providers are tried in order:
1. CoinGecko (free, no API key needed for basic usage)
2. Kraken (public API, good reliability)
3. CoinCap (free tier available)
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class PriceProvider(ABC):
    """Abstract base class for price providers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging."""
        pass
    
    @abstractmethod
    async def get_btc_price(self, client: httpx.AsyncClient) -> Optional[float]:
        """Get current BTC/USD price. Returns None on failure."""
        pass
    
    @abstractmethod
    async def get_btc_ohlc(self, client: httpx.AsyncClient, limit: int = 250) -> Optional[list]:
        """
        Get BTC/USD OHLC data.
        Returns list of [timestamp, open, high, low, close, volume] or None.
        """
        pass


class CoinGeckoProvider(PriceProvider):
    """
    CoinGecko free API.
    
    Rate limits:
    - Free: ~10-30 calls/minute
    - No API key required for basic endpoints
    
    Note: Only provides daily OHLC for free tier.
    """
    
    @property
    def name(self) -> str:
        return "CoinGecko"
    
    async def get_btc_price(self, client: httpx.AsyncClient) -> Optional[float]:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin",
            "vs_currencies": "usd",
        }
        
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 429:
                logger.warning(f"{self.name}: rate limited")
                return None
            resp.raise_for_status()
            data = resp.json()
            return float(data["bitcoin"]["usd"])
        except Exception as e:
            logger.debug(f"{self.name}: price fetch failed: {e}")
            return None
    
    async def get_btc_ohlc(self, client: httpx.AsyncClient, limit: int = 250) -> Optional[list]:
        # CoinGecko free tier only provides daily OHLC
        url = "https://api.coingecko.com/api/v3/coins/bitcoin/ohlc"
        params = {"vs_currency": "usd", "days": "max"}
        
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 429:
                return None
            resp.raise_for_status()
            data = resp.json()
            # Convert to [timestamp, open, high, low, close, volume] format
            # CoinGecko returns: [timestamp, open, high, low, close]
            return [[row[0], row[1], row[2], row[3], row[4], 0] for row in data[-limit:]]
        except Exception as e:
            logger.debug(f"{self.name}: OHLC fetch failed: {e}")
            return None


class KrakenProvider(PriceProvider):
    """
    Kraken public API.
    
    Rate limits:
    - Public endpoints: ~1 call/second sustained
    - No API key required
    
    Provides real-time OHLC data.
    """
    
    @property
    def name(self) -> str:
        return "Kraken"
    
    async def get_btc_price(self, client: httpx.AsyncClient) -> Optional[float]:
        url = "https://api.kraken.com/0/public/Ticker"
        params = {"pair": "XBTUSD"}
        
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                logger.debug(f"{self.name}: API error: {data['error']}")
                return None
            # Kraken returns price as string array [price, whole_lot_volume]
            result = data.get("result", {})
            for pair_data in result.values():
                return float(pair_data["c"][0])  # Last trade close price
            return None
        except Exception as e:
            logger.debug(f"{self.name}: price fetch failed: {e}")
            return None
    
    async def get_btc_ohlc(self, client: httpx.AsyncClient, limit: int = 250) -> Optional[list]:
        url = "https://api.kraken.com/0/public/OHLC"
        # Kraken supports: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600 (minutes)
        params = {"pair": "XBTUSD", "interval": 5, "count": limit}
        
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                logger.debug(f"{self.name}: API error: {data['error']}")
                return None
            result = data.get("result", {})
            for pair_data in result.values():
                # Kraken format: [time, etime, open, high, low, close, vwap, volume, count]
                ohlc = []
                for row in pair_data:
                    ohlc.append([
                        int(float(row[0]) * 1000),  # timestamp in ms
                        float(row[2]),  # open
                        float(row[3]),  # high
                        float(row[4]),  # low
                        float(row[5]),  # close
                        float(row[7]),  # volume
                    ])
                return ohlc
            return None
        except Exception as e:
            logger.debug(f"{self.name}: OHLC fetch failed: {e}")
            return None


class CoinCapProvider(PriceProvider):
    """
    CoinCap API v2.
    
    Rate limits:
    - Free: 200 requests/minute
    - No API key required for basic usage
    
    Note: Limited historical data available.
    """
    
    @property
    def name(self) -> str:
        return "CoinCap"
    
    async def get_btc_price(self, client: httpx.AsyncClient) -> Optional[float]:
        url = "https://api.coincap.io/v2/assets/bitcoin"
        
        try:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code == 429:
                logger.warning(f"{self.name}: rate limited")
                return None
            resp.raise_for_status()
            data = resp.json()
            return float(data["data"]["priceUsd"])
        except Exception as e:
            logger.debug(f"{self.name}: price fetch failed: {e}")
            return None
    
    async def get_btc_ohlc(self, client: httpx.AsyncClient, limit: int = 250) -> Optional[list]:
        url = "https://api.coincap.io/v2/assets/bitcoin/history"
        params = {"interval": "d1"}  # daily candles
        
        try:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code == 429:
                return None
            resp.raise_for_status()
            data = resp.json()
            # CoinCap format: [time, price]
            # This is not true OHLC, just daily price points
            # We'll approximate OHLC from price series
            ohlc = []
            history = data.get("data", [])[-limit:]
            
            for i, point in enumerate(history):
                price = float(point["priceUsd"])
                ts = point["time"]
                # Approximate OHLC from price (use same price for all)
                ohlc.append([ts, price, price, price, price, 0])
            
            return ohlc
        except Exception as e:
            logger.debug(f"{self.name}: OHLC fetch failed: {e}")
            return None


class FallbackChain:
    """
    Manages fallback between multiple providers.
    
    When the primary source (Binance) fails, tries providers in order.
    Tracks provider health to avoid repeatedly failing providers.
    """
    
    def __init__(self, providers: Optional[list[PriceProvider]] = None):
        self._providers = providers or [
            CoinGeckoProvider(),
            KrakenProvider(),
            CoinCapProvider(),
        ]
        self._provider_health: dict[str, dict] = {
            p.name: {"failures": 0, "last_failure": 0, "cooldown_until": 0}
            for p in self._providers
        }
        self._lock = asyncio.Lock()
        
        # Cooldown settings
        self._max_failures = 3
        self._cooldown_base = 60  # seconds
        self._cooldown_multiplier = 2
    
    async def get_btc_price(self, client: httpx.AsyncClient) -> tuple[Optional[float], str]:
        """
        Try providers in order until one succeeds.
        
        Returns (price, provider_name) tuple.
        """
        now = time.time()
        
        for provider in self._providers:
            name = provider.name
            health = self._provider_health[name]
            
            # Skip if in cooldown
            if now < health["cooldown_until"]:
                continue
            
            try:
                price = await provider.get_btc_price(client)
                if price is not None and price > 0:
                    # Reset failure count on success
                    async with self._lock:
                        self._provider_health[name]["failures"] = 0
                    logger.info(f"Fallback: got BTC price ${price:.2f} from {name}")
                    return price, name
            except Exception as e:
                logger.debug(f"Fallback: {name} threw exception: {e}")
            
            # Record failure
            async with self._lock:
                health = self._provider_health[name]
                health["failures"] += 1
                health["last_failure"] = now
                
                if health["failures"] >= self._max_failures:
                    cooldown = self._cooldown_base * (self._cooldown_multiplier ** (health["failures"] - self._max_failures))
                    health["cooldown_until"] = now + cooldown
                    logger.warning(f"Fallback: {name} in cooldown for {cooldown}s after {health['failures']} failures")
        
        return None, ""
    
    async def get_btc_ohlc(self, client: httpx.AsyncClient, limit: int = 250) -> tuple[Optional[list], str]:
        """
        Try providers for OHLC data.
        
        Returns (ohlc_data, provider_name) tuple.
        Note: Fallback OHLC is typically lower resolution than Binance.
        """
        now = time.time()
        
        for provider in self._providers:
            name = provider.name
            health = self._provider_health[name]
            
            # Skip if in cooldown
            if now < health["cooldown_until"]:
                continue
            
            try:
                ohlc = await provider.get_btc_ohlc(client, limit)
                if ohlc:
                    async with self._lock:
                        self._provider_health[name]["failures"] = 0
                    logger.info(f"Fallback: got {len(ohlc)} OHLC candles from {name}")
                    return ohlc, name
            except Exception as e:
                logger.debug(f"Fallback: {name} OHLC threw exception: {e}")
            
            # Record failure
            async with self._lock:
                health = self._provider_health[name]
                health["failures"] += 1
                health["last_failure"] = now
        
        return None, ""
    
    def get_health_status(self) -> dict:
        """Get current health status of all providers."""
        now = time.time()
        return {
            name: {
                "failures": health["failures"],
                "in_cooldown": now < health["cooldown_until"],
                "cooldown_remaining": max(0, health["cooldown_until"] - now),
            }
            for name, health in self._provider_health.items()
        }


fallback_chain = FallbackChain()