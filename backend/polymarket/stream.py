"""
Polymarket WebSocket client for real-time market data.

Maintains a persistent connection to the CLOB WebSocket and keeps
a local price cache updated in real-time.  This replaces HTTP polling
for price monitoring, enabling sub-second stop-loss reactions.

Channels used:
  - Market channel: book updates, price changes for subscribed tokens

Endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/market
Rate limits: max 500 instruments per connection (we use 2-4).
"""

import asyncio
import json
import logging
import time
import ssl
import certifi
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed

from config import POLYMARKET_WS_HOST

logger = logging.getLogger(__name__)


class PriceCache:
    """In-memory price cache updated by the WebSocket stream."""

    def __init__(self):
        self._prices: dict[str, dict] = {}

    def update(
        self,
        token_id: str,
        *,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        mid: Optional[float] = None,
    ):
        """Update cached prices for a token. Derives midpoint from bid/ask if not given."""
        entry = self._prices.get(
            token_id,
            {"bid": None, "ask": None, "mid": None, "last_update": 0.0},
        )
        if bid is not None:
            entry["bid"] = bid
        if ask is not None:
            entry["ask"] = ask
        if mid is not None:
            entry["mid"] = mid
        elif bid is not None and ask is not None and bid > 0 and ask > 0:
            entry["mid"] = round((bid + ask) / 2, 4)
        entry["last_update"] = time.time()
        self._prices[token_id] = entry

    def get_midpoint(self, token_id: str) -> Optional[float]:
        entry = self._prices.get(token_id)
        if not entry:
            return None
        return entry.get("mid")

    def get_best_bid(self, token_id: str) -> Optional[float]:
        entry = self._prices.get(token_id)
        if not entry:
            return None
        return entry.get("bid")

    def get_best_ask(self, token_id: str) -> Optional[float]:
        entry = self._prices.get(token_id)
        if not entry:
            return None
        return entry.get("ask")

    def get_age_seconds(self, token_id: str) -> float:
        """How stale is the cached price, in seconds."""
        entry = self._prices.get(token_id)
        if not entry or entry["last_update"] == 0:
            return float("inf")
        return time.time() - entry["last_update"]

    def clear(self):
        self._prices.clear()


class MarketDataStream:
    """
    Persistent WebSocket connection to Polymarket CLOB for real-time prices.

    Usage::

        stream = MarketDataStream()
        await stream.start()
        stream.subscribe([token_id_up, token_id_down])
        price = stream.prices.get_midpoint(token_id_up)
        ...
        await stream.stop()
    """

    WS_MARKET_URL = f"{POLYMARKET_WS_HOST}/ws/market"
    RECONNECT_DELAY_BASE = 1.0
    RECONNECT_DELAY_MAX = 30.0
    STALE_THRESHOLD_SECONDS = 10.0

    def __init__(self):
        self.prices = PriceCache()
        self._ws = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._subscribed_tokens: set[str] = set()
        self._connected = False
        self._reconnect_delay = self.RECONNECT_DELAY_BASE

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscribed_tokens(self) -> set[str]:
        return self._subscribed_tokens.copy()

    async def start(self):
        """Start the WebSocket listener as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("MarketDataStream started")

    async def stop(self):
        """Gracefully shut down the WebSocket connection."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._connected = False
        logger.info("MarketDataStream stopped")

    def subscribe(self, token_ids: list[str]):
        """
        Subscribe to price updates for the given token IDs.

        Sends the subscription message immediately if connected,
        otherwise the tokens are queued and subscribed on (re)connect.
        """
        new_tokens = [t for t in token_ids if t and t not in self._subscribed_tokens]
        if not new_tokens:
            return
        self._subscribed_tokens.update(new_tokens)
        if self._ws and self._connected:
            asyncio.create_task(self._send_subscribe(new_tokens))

    def unsubscribe(self, token_ids: list[str]):
        """Remove tokens from the active subscription set."""
        for t in token_ids:
            self._subscribed_tokens.discard(t)

    def is_price_fresh(self, token_id: str) -> bool:
        """Return True if we have a recent price for *token_id*."""
        return self.prices.get_age_seconds(token_id) < self.STALE_THRESHOLD_SECONDS

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self):
        """Main loop: connect, listen, reconnect on failure."""
        # Create SSL context with certifi certificates to avoid verify failed errors
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        
        while self._running:
            try:
                logger.info(f"Connecting to {self.WS_MARKET_URL} ...")
                async with websockets.connect(
                    self.WS_MARKET_URL,
                    ssl=ssl_context,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    self._connected = True
                    self._reconnect_delay = self.RECONNECT_DELAY_BASE
                    logger.info("MarketDataStream connected")

                    # Re-subscribe to all active tokens on (re)connect
                    if self._subscribed_tokens:
                        await self._send_subscribe(list(self._subscribed_tokens))

                    async for raw_msg in ws:
                        try:
                            self._handle_message(raw_msg)
                        except Exception as exc:
                            logger.debug(f"Error handling WS message: {exc}")

            except ConnectionClosed as exc:
                logger.warning(f"MarketDataStream connection closed: {exc}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"MarketDataStream error: {exc}")

            self._connected = False
            self._ws = None

            if self._running:
                logger.info(f"Reconnecting in {self._reconnect_delay:.1f}s ...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self.RECONNECT_DELAY_MAX,
                )

    async def _send_subscribe(self, token_ids: list[str]):
        """Send a subscription message for the given tokens."""
        if not self._ws or not self._connected:
            return
        msg = {"assets_ids": token_ids, "type": "market"}
        try:
            await self._ws.send(json.dumps(msg))
            short = [t[:16] + "..." for t in token_ids]
            logger.info(f"Subscribed to {len(token_ids)} token(s): {short}")
        except Exception as exc:
            logger.error(f"Error sending subscribe: {exc}")

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    def _handle_message(self, raw: str):
        """Parse an incoming WS message and update the price cache."""
        data = json.loads(raw)
        events = data if isinstance(data, list) else [data]

        for event in events:
            event_type = event.get("event_type")
            asset_id = event.get("asset_id")
            if not asset_id or asset_id not in self._subscribed_tokens:
                continue

            if event_type == "book":
                self._process_book_event(event, asset_id)
            elif event_type in ("price_change", "last_trade_price"):
                self._process_price_event(event, asset_id)

    def _process_book_event(self, event: dict, asset_id: str):
        """Extract best bid/ask from an order-book snapshot event."""
        best_bid = self._extract_best_price(event.get("bids", []))
        best_ask = self._extract_best_price(event.get("asks", []))
        if best_bid is not None or best_ask is not None:
            self.prices.update(asset_id, bid=best_bid, ask=best_ask)

    @staticmethod
    def _extract_best_price(levels: list) -> Optional[float]:
        """Return the first price from an order-book level list.

        Handles both dict-style ``[{"price": "0.54", ...}]``
        and array-style ``[["0.54", "100"], ...]`` formats.
        """
        if not levels:
            return None
        first = levels[0]
        try:
            if isinstance(first, dict):
                return float(first.get("price", first.get("p", 0)))
            if isinstance(first, (list, tuple)):
                return float(first[0])
            return float(first)
        except (ValueError, IndexError, TypeError):
            return None

    def _process_price_event(self, event: dict, asset_id: str):
        """Extract the price from a price_change or last_trade_price event."""
        price = event.get("price")
        if price is not None:
            try:
                self.prices.update(asset_id, mid=float(price))
            except (ValueError, TypeError):
                pass


# Global singleton
market_stream = MarketDataStream()
