"""
Binance API Rate Limiter.

Implements token bucket algorithm to stay under Binance rate limits:
- 6,000 weight per minute (REQUEST_WEIGHT)
- 61,000 raw requests per 5 minutes (RAW_REQUESTS)

Handles:
- 429 (rate limit exceeded) with Retry-After header
- 418 (IP auto-banned) with backoff
- X-MBX-USED-WEIGHT header tracking
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Rate limit constants
WEIGHT_LIMIT_PER_MINUTE = 6000
RAW_REQUEST_LIMIT_5MIN = 61000

# Endpoint weights (approximate based on Binance docs)
ENDPOINT_WEIGHTS = {
    "/api/v3/klines": 2,  # 2 weight per request (varies by limit)
    "/api/v3/depth": 2,  # 2-10 weight depending on limit
    "/api/v3/ticker/price": 2,
    "/api/v3/exchangeInfo": 20,
}

# Weight multipliers based on limit parameter
KLINE_WEIGHT_BY_LIMIT = {
    100: 2,
    250: 5,
    500: 10,
    1000: 20,
}

DEPTH_WEIGHT_BY_LIMIT = {
    5: 2,
    10: 10,
    20: 20,
    50: 50,
    100: 100,
    500: 250,
}


@dataclass
class RateLimitState:
    """Tracks current rate limit state."""
    used_weight_1m: int = 0
    used_weight_5m: int = 0
    last_weight_update: float = 0
    request_count_5m: int = 0
    last_request_time: float = 0
    ban_until: float = 0
    consecutive_429s: int = 0


class BinanceRateLimiter:
    """
    Token bucket rate limiter for Binance API.
    
    Features:
    - Tracks request weight per minute
    - Automatic backoff on 429/418
    - Respects Retry-After header
    - Prevents IP bans by proactive throttling
    """
    
    def __init__(
        self,
        max_weight_per_minute: int = WEIGHT_LIMIT_PER_MINUTE,
        weight_buffer: float = 0.8,
        min_request_interval: float = 0.1,
    ):
        self._max_weight = max_weight_per_minute
        self._weight_buffer = weight_buffer  # Use only 80% of limit
        self._min_interval = min_request_interval
        self._state = RateLimitState()
        self._lock = asyncio.Lock()
        self._weight_per_second = self._max_weight / 60.0
        
    @property
    def effective_limit(self) -> int:
        """The effective weight limit (with buffer)."""
        return int(self._max_weight * self._weight_buffer)
    
    def _get_endpoint_weight(self, endpoint: str, params: dict) -> int:
        """Calculate request weight for an endpoint."""
        if "/api/v3/klines" in endpoint:
            limit = params.get("limit", 250)
            return KLINE_WEIGHT_BY_LIMIT.get(limit, 5)
        elif "/api/v3/depth" in endpoint:
            limit = params.get("limit", 5)
            return DEPTH_WEIGHT_BY_LIMIT.get(limit, 2)
        elif "/api/v3/ticker/price" in endpoint:
            return 2
        elif "/api/v3/exchangeInfo" in endpoint:
            return 20
        else:
            return 5
    
    async def acquire(self, endpoint: str, params: dict) -> float:
        """
        Acquire permission to make a request.
        
        Returns the delay needed before making the request.
        Blocks if rate limit would be exceeded.
        """
        weight = self._get_endpoint_weight(endpoint, params)
        
        async with self._lock:
            now = time.time()
            
            # Check if banned
            if now < self._state.ban_until:
                wait_time = self._state.ban_until - now
                logger.warning(f"Rate limiter: BANNED for {wait_time:.0f}s more")
                return wait_time
            
            # Decay weight based on time passed
            elapsed = now - self._state.last_weight_update
            decayed_weight = elapsed * self._weight_per_second
            self._state.used_weight_1m = max(0, self._state.used_weight_1m - decayed_weight)
            self._state.last_weight_update = now
            
            # Check if we need to wait
            projected_weight = self._state.used_weight_1m + weight
            if projected_weight > self.effective_limit:
                wait_time = (projected_weight - self.effective_limit) / self._weight_per_second
                wait_time = max(wait_time, self._min_interval)
                logger.debug(f"Rate limiter: waiting {wait_time:.2f}s (weight: {projected_weight}/{self.effective_limit})")
                return wait_time
            
            # Enforce minimum interval
            time_since_last = now - self._state.last_request_time
            if time_since_last < self._min_interval:
                return self._min_interval - time_since_last
            
            return 0.0
    
    async def record_request(self, endpoint: str, params: dict):
        """Record that a request was made."""
        weight = self._get_endpoint_weight(endpoint, params)
        
        async with self._lock:
            self._state.used_weight_1m += weight
            self._state.request_count_5m += 1
            self._state.last_request_time = time.time()
            self._state.last_weight_update = time.time()
    
    async def handle_response_headers(self, headers: dict):
        """Process rate limit headers from Binance response."""
        async with self._lock:
            # Extract weight from headers
            for key, value in headers.items():
                if key.upper().startswith("X-MBX-USED-WEIGHT"):
                    try:
                        weight = int(value)
                        if "1M" in key.upper():
                            self._state.used_weight_1m = weight
                        elif "5M" in key.upper():
                            self._state.used_weight_5m = weight
                        self._state.last_weight_update = time.time()
                    except (ValueError, TypeError):
                        pass
    
    async def handle_429(self, headers: dict) -> float:
        """
        Handle 429 rate limit response.
        
        Returns the wait time from Retry-After header or default.
        """
        retry_after = headers.get("Retry-After", "60")
        try:
            wait_time = int(retry_after)
        except (ValueError, TypeError):
            wait_time = 60
        
        async with self._lock:
            self._state.consecutive_429s += 1
            logger.warning(
                f"Rate limiter: 429 received (#{self._state.consecutive_429s}), "
                f"waiting {wait_time}s"
            )
        
        return float(wait_time)
    
    async def handle_418(self, headers: dict) -> float:
        """
        Handle 418 IP ban response.
        
        Returns the wait time and updates ban state.
        """
        retry_after = headers.get("Retry-After")
        
        async with self._lock:
            # Escalating ban times: 2min -> 5min -> 10min -> 30min -> 1hr -> 3hr -> 1day -> 3days
            ban_multipliers = [120, 300, 600, 1800, 3600, 10800, 86400, 259200]
            ban_index = min(self._state.consecutive_429s, len(ban_multipliers) - 1)
            base_ban = ban_multipliers[ban_index]
            
            if retry_after:
                try:
                    wait_time = int(retry_after)
                except (ValueError, TypeError):
                    wait_time = base_ban
            else:
                wait_time = base_ban
            
            self._state.ban_until = time.time() + wait_time
            self._state.consecutive_429s += 1
            
            logger.error(
                f"Rate limiter: 418 BANNED for {wait_time}s "
                f"(until {time.strftime('%H:%M:%S', time.localtime(self._state.ban_until))})"
            )
        
        return float(wait_time)
    
    async def record_success(self):
        """Record a successful request (resets consecutive 429 counter)."""
        async with self._lock:
            self._state.consecutive_429s = 0
    
    def get_state(self) -> dict:
        """Get current rate limiter state for monitoring."""
        return {
            "used_weight_1m": self._state.used_weight_1m,
            "effective_limit": self.effective_limit,
            "request_count_5m": self._state.request_count_5m,
            "is_banned": time.time() < self._state.ban_until,
            "ban_remaining": max(0, self._state.ban_until - time.time()),
            "consecutive_429s": self._state.consecutive_429s,
        }


binance_rate_limiter = BinanceRateLimiter()