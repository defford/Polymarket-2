"""
Polymarket CLOB client wrapper.
Handles initialization, authentication, and common operations.

ASYNC version with:
- asyncio.to_thread() wrappers for py-clob-client calls
- Price history caching with TTL
"""

import asyncio
import logging
import time
from typing import Optional

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs, MarketOrderArgs, OrderType, BookParams,
    BalanceAllowanceParams, AssetType,
)
from py_clob_client.order_builder.constants import BUY, SELL

from config import (
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_PROXY_ADDRESS,
    POLYMARKET_CLOB_HOST,
    CHAIN_ID,
)

logger = logging.getLogger(__name__)

PRICE_HISTORY_CACHE_TTL = 5.0
ORDERBOOK_CACHE_TTL = 2.0


class PolymarketClient:
    """
    Wrapper around py-clob-client for Polymarket CLOB API.
    Supports both read-only and authenticated modes.
    
    All CLOB operations are wrapped in asyncio.to_thread() to avoid
    blocking the async event loop since py-clob-client is synchronous.
    """

    def __init__(self):
        self._client: Optional[ClobClient] = None
        self._authenticated = False
        self._http: Optional[httpx.AsyncClient] = None
        self._price_history_cache: dict[str, tuple[list, float]] = {}
        self._orderbook_cache: dict[str, tuple[dict, float]] = {}
        self._midpoint_cache: dict[str, tuple[float, float]] = {}

    def init_read_only(self):
        """Initialize a read-only client (no auth needed)."""
        self._client = ClobClient(POLYMARKET_CLOB_HOST)
        self._authenticated = False
        logger.info("Polymarket client initialized (read-only)")

    def init_authenticated(self):
        """Initialize an authenticated client for trading."""
        if not POLYMARKET_PRIVATE_KEY or not POLYMARKET_PROXY_ADDRESS:
            raise ValueError(
                "POLYMARKET_PRIVATE_KEY and POLYMARKET_PROXY_ADDRESS must be set "
                "in .env to trade. Export your private key from Polymarket: "
                "Settings → Advanced → Export Private Key"
            )

        self._client = ClobClient(
            host=POLYMARKET_CLOB_HOST,
            key=POLYMARKET_PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=1,
            funder=POLYMARKET_PROXY_ADDRESS if POLYMARKET_PROXY_ADDRESS else None,
        )
        self._client.set_api_creds(self._client.create_or_derive_api_creds())

        try:
            ba = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            raw_allowance = float(ba.get("allowance", 0))
            current_allowance = raw_allowance / 1_000_000
            
            logger.info(f"Initial Allowance Check: {raw_allowance} (approx ${current_allowance:,.2f})")

            if current_allowance < 1_000:  
                logger.info("Allowance is low (< $1000). Attempting to set max allowance...")
                try:
                    logger.info("Approving COLLATERAL (USDC)...")
                    resp = self._client.update_balance_allowance(
                        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                    )
                    logger.info(f"USDC Approval TX: {resp}")
                    
                    import time as time_module
                    for i in range(5):
                        time_module.sleep(2.0)
                        ba_check = self._client.get_balance_allowance(
                            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                        )
                        new_raw = float(ba_check.get("allowance", 0))
                        new_human = new_raw / 1_000_000
                        logger.info(f"Allowance poll #{i+1}: ${new_human:,.2f}")
                        if new_human > 1_000:
                            logger.info("Allowance updated successfully!")
                            break
                    else:
                        logger.warning("Allowance did not update within 10s. Transaction might be pending or failed.")
                        
                except Exception as e:
                    logger.error(f"Failed to send allowance update transaction: {e}")
            else:
                logger.info("Allowance is already sufficient.")

        except Exception as e:
            logger.warning(f"Failed to check/update allowance: {e}")

        try:
            ba = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            raw_bal = float(ba.get("balance", 0))
            raw_allow = float(ba.get("allowance", 0))
            
            bal_usdc = raw_bal / 1_000_000
            allow_usdc = raw_allow / 1_000_000
            
            target_address = POLYMARKET_PROXY_ADDRESS if POLYMARKET_PROXY_ADDRESS else "Signer (EOA)"
            logger.info(f"Account State [{target_address}] -- Balance: ${bal_usdc:,.2f} | Allowance: ${allow_usdc:,.2f}")

            if bal_usdc < 5.0:
                logger.warning(f"Low balance on {target_address}! You have ${bal_usdc:.2f}, but need at least $5.00 for a trade.")
                logger.warning("If you deposited funds, make sure they are in the PROXY address (if configured), not the Signer.")
            
            if allow_usdc < 5.0:
                logger.warning(f"Low allowance (${allow_usdc:.2f})! Orders will likely fail.")
                
        except Exception as e:
            logger.error(f"Could not verify balance/allowance: {e}")

        self._authenticated = True
        logger.info("Polymarket client initialized (authenticated)")

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazy initialization of async HTTP client."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def close(self):
        """Close the HTTP client connection."""
        if self._http:
            await self._http.aclose()
            self._http = None

    @property
    def client(self) -> ClobClient:
        if self._client is None:
            raise RuntimeError("Client not initialized. Call init_read_only() or init_authenticated() first.")
        return self._client

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    def _require_auth(self):
        if not self._authenticated:
            raise RuntimeError(
                "Authenticated client required for this operation. "
                "Call init_authenticated() first."
            )

    # --- Read Operations (async wrappers) ---

    async def get_midpoint(self, token_id: str) -> tuple[float, bool]:
        """
        Get midpoint price for a token (async, cached).
        
        Returns:
            tuple: (midpoint_price, market_exists)
            - midpoint_price: The midpoint price (0.5 fallback if unavailable)
            - market_exists: False if the market/orderbook no longer exists (404)
        """
        now = time.time()
        cached = self._midpoint_cache.get(token_id)
        if cached and (now - cached[1]) < ORDERBOOK_CACHE_TTL:
            return cached[0], True
        
        try:
            result = await asyncio.to_thread(self.client.get_midpoint, token_id)
            midpoint = float(result.get("mid", 0.5))
            self._midpoint_cache[token_id] = (midpoint, now)
            return midpoint, True
        except Exception as e:
            error_str = str(e)
            # Check if this is a "market closed" scenario (404 - no orderbook)
            if "404" in error_str or "No orderbook exists" in error_str:
                logger.debug(f"Market closed for token {token_id[:16]}... (no orderbook)")
                return cached[0] if cached else 0.5, False
            else:
                logger.error(f"Error getting midpoint for {token_id}: {e}")
                return cached[0] if cached else 0.5, True

    async def get_price(self, token_id: str, side: str = "BUY") -> float:
        """Get best price for a token on a given side (async)."""
        try:
            result = await asyncio.to_thread(self.client.get_price, token_id, side=side)
            return float(result.get("price", 0.5))
        except Exception as e:
            logger.error(f"Error getting price for {token_id}: {e}")
            return 0.5

    async def get_order_book(self, token_id: str) -> dict:
        """Get full order book for a token (async, cached briefly)."""
        now = time.time()
        cached = self._orderbook_cache.get(token_id)
        if cached and (now - cached[1]) < ORDERBOOK_CACHE_TTL:
            return cached[0]
        
        try:
            result = await asyncio.to_thread(self.client.get_order_book, token_id)
            self._orderbook_cache[token_id] = (result, now)
            return result
        except Exception as e:
            logger.error(f"Error getting order book for {token_id}: {e}")
            return cached[0] if cached else {"bids": [], "asks": []}

    async def get_order_books(self, token_ids: list[str]) -> list[dict]:
        """Get order books for multiple tokens (async, parallel)."""
        try:
            params = [BookParams(token_id=tid) for tid in token_ids]
            return await asyncio.to_thread(self.client.get_order_books, params)
        except Exception as e:
            logger.error(f"Error getting order books: {e}")
            return []

    async def get_price_history(self, token_id: str, interval: str = "max", fidelity: int = 60) -> list:
        """
        Get historical price data for a token via direct HTTP call (async, cached).
        
        Args:
            token_id: The token to fetch price history for
            interval: Time range - options: 1d, 1w, 1m (month), max (default: max)
            fidelity: Seconds between data points (default: 60 for ~1 minute resolution)
            
        Returns:
            List of price history data points [{t: timestamp, p: price}, ...]
        """
        cache_key = f"{token_id}:{interval}:{fidelity}"
        now = time.time()
        
        cached = self._price_history_cache.get(cache_key)
        if cached and (now - cached[1]) < PRICE_HISTORY_CACHE_TTL:
            return cached[0]
        
        try:
            http_client = await self._get_http_client()
            resp = await http_client.get(
                f"{POLYMARKET_CLOB_HOST}/prices-history",
                params={
                    "market": token_id,
                    "interval": interval,
                    "fidelity": fidelity,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            history = data.get("history", []) if isinstance(data, dict) else data
            self._price_history_cache[cache_key] = (history, now)
            return history
        except httpx.HTTPStatusError as e:
            logger.warning(f"Price history not available for token {token_id[:16]}...: HTTP {e.response.status_code}")
            return cached[0] if cached else []
        except Exception as e:
            logger.error(f"Error getting price history for {token_id}: {e}")
            return cached[0] if cached else []

    async def get_markets(self) -> list:
        """Get all available markets from the CLOB (async)."""
        try:
            return await asyncio.to_thread(self.client.get_markets)
        except Exception as e:
            logger.error(f"Error getting markets: {e}")
            return []

    async def get_market(self, condition_id: str) -> dict:
        """Get a specific market by condition ID (async)."""
        try:
            return await asyncio.to_thread(self.client.get_market, condition_id)
        except Exception as e:
            logger.error(f"Error getting market {condition_id}: {e}")
            return {}

    # --- Write Operations (auth required, async) ---

    async def place_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
        post_only: bool = True,
    ) -> dict:
        """Place a limit order (async)."""
        self._require_auth()

        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY if side == "BUY" else SELL,
            token_id=token_id,
        )

        try:
            signed_order = await asyncio.to_thread(self.client.create_order, order_args)
            resp = await asyncio.to_thread(self.client.post_order, signed_order, OrderType.GTC)
            logger.info(
                f"Limit order placed: {side} {size} @ {price} "
                f"(token={token_id[:16]}..., postOnly={post_only}) -> {resp}"
            )
            return resp
        except Exception as e:
            logger.error(f"Error placing limit order: {e}")
            
            try:
                ba = await asyncio.to_thread(
                    self._client.get_balance_allowance,
                    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                )
                raw_bal = float(ba.get("balance", 0))
                raw_allow = float(ba.get("allowance", 0))
                bal_usdc = raw_bal / 1_000_000
                allow_usdc = raw_allow / 1_000_000
                logger.warning(f"Diagnostic [Failure]: Balance=${bal_usdc:,.2f} | Allowance=${allow_usdc:,.2f}")
            except:
                pass

            return {"success": False, "errorMsg": str(e)}

    async def place_market_order(
        self,
        token_id: str,
        amount: float,
        side: str = "BUY",
    ) -> dict:
        """Place a FOK market order (async)."""
        self._require_auth()

        mo = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=BUY if side == "BUY" else SELL,
        )

        try:
            signed_order = await asyncio.to_thread(self.client.create_market_order, mo)
            resp = await asyncio.to_thread(self.client.post_order, signed_order, OrderType.FOK)

            logger.info(
                f"Market order placed: {side} ${amount} "
                f"(token={token_id[:16]}...) -> {resp}"
            )
            return resp
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            
            try:
                ba = await asyncio.to_thread(
                    self._client.get_balance_allowance,
                    BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                )
                raw_bal = float(ba.get("balance", 0))
                raw_allow = float(ba.get("allowance", 0))
                bal_usdc = raw_bal / 1_000_000
                allow_usdc = raw_allow / 1_000_000
                logger.warning(f"Diagnostic [Failure]: Balance=${bal_usdc:,.2f} | Allowance=${allow_usdc:,.2f}")
            except:
                pass

            return {"success": False, "errorMsg": str(e)}

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order (async)."""
        self._require_auth()
        try:
            return await asyncio.to_thread(self.client.cancel, order_id)
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return {"success": False, "errorMsg": str(e)}

    async def cancel_all_orders(self) -> dict:
        """Cancel all open orders (async)."""
        self._require_auth()
        try:
            return await asyncio.to_thread(self.client.cancel_all)
        except Exception as e:
            logger.error(f"Error cancelling all orders: {e}")
            return {"success": False, "errorMsg": str(e)}

    async def get_open_orders(self) -> list:
        """Get all open orders for the authenticated user (async)."""
        self._require_auth()
        try:
            return await asyncio.to_thread(self.client.get_orders)
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    async def get_trades(self) -> list:
        """Get trade history for the authenticated user (async)."""
        self._require_auth()
        try:
            return await asyncio.to_thread(self.client.get_trades)
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []

    async def get_order(self, order_id: str) -> dict:
        """Get details of a specific order (async)."""
        self._require_auth()
        try:
            return await asyncio.to_thread(self.client.get_order, order_id)
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return {}

    def clear_cache(self):
        """Clear all caches."""
        self._price_history_cache.clear()
        self._orderbook_cache.clear()
        self._midpoint_cache.clear()


polymarket_client = PolymarketClient()
