"""
ExchangeSession: per-batch exchange coordinator.

Responsibilities:
  - Cache margin mode and leverage initialization per symbol (at most once each)
  - Bound concurrent API calls via asyncio.Semaphore
  - Pre-warm WebSocket order book connections on initialize()
  - Track WebSocket circuit breaker state
"""

from __future__ import annotations

import asyncio
import logging

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.order_executor.event_bus import OrderEventBus

_log = logging.getLogger(__name__)


class ExchangeSession:
    """
    Per-batch coordination context injected into order executors.

    Does NOT execute orders itself. Provides:
      - Symbol-level margin/leverage initialization cache
      - Bounded concurrency via asyncio.Semaphore
      - WS circuit breaker state
    """

    @beartype
    def __init__(
        self,
        exchange: Exchange,
        event_bus: OrderEventBus,
        max_concurrent_orders: int = 5,
    ) -> None:
        self._exchange = exchange
        self._event_bus = event_bus
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent_orders)
        self._circuit_open: bool = False
        self.margin_initialized: set[str] = set()

    @beartype
    async def initialize(self, symbol: str) -> None:
        """
        Pre-warm the WS order book connection before any order is submitted.

        Only invoked on WS-capable exchanges. Pre-warm failure is non-fatal:
        the exception is logged at DEBUG level and not re-raised.
        """
        if not self._exchange.has_ws_support():
            _log.debug(
                "%s - exchange has no WS support; skipping order book pre-warm",
                self._exchange.id,
            )
            return

        try:
            await self._exchange.api.watch_order_book(symbol)
            _log.debug(
                "%s - WS order book pre-warmed for %s",
                self._exchange.id,
                symbol,
            )
        except Exception:  # noqa: BLE001
            _log.debug(
                "%s - WS order book pre-warm failed for %s (non-fatal)",
                self._exchange.id,
                symbol,
                exc_info=True,
            )

    @beartype
    async def ensure_margin_initialized(self, symbol: str) -> None:
        """
        Call set_margin_mode and set_leverage exactly once per symbol per session.

        Subsequent calls for the same symbol are no-ops. Failures are logged at
        DEBUG level and not re-raised — initialization failure is treated as
        best-effort (exchange may not require it).
        """
        if symbol in self.margin_initialized:
            return

        try:
            await self._exchange.api.set_margin_mode("isolated", symbol)
            _log.debug(
                "%s - set_margin_mode(isolated) done for %s",
                self._exchange.id,
                symbol,
            )
        except Exception:  # noqa: BLE001
            _log.debug(
                "%s - set_margin_mode failed for %s (non-fatal)",
                self._exchange.id,
                symbol,
                exc_info=True,
            )

        try:
            await self._exchange.api.set_leverage(self._exchange.leverage, symbol)
            _log.debug(
                "%s - set_leverage(%s) done for %s",
                self._exchange.id,
                self._exchange.leverage,
                symbol,
            )
        except Exception:  # noqa: BLE001
            _log.debug(
                "%s - set_leverage failed for %s (non-fatal)",
                self._exchange.id,
                symbol,
                exc_info=True,
            )

        self.margin_initialized.add(symbol)

    @beartype
    def mark_circuit_open(self) -> None:
        """Transition the session to REST-only mode."""
        self._circuit_open = True
        _log.debug("%s - WS circuit breaker opened; session now REST-only", self._exchange.id)

    @beartype
    def is_circuit_open(self) -> bool:
        """Return True if the WS circuit breaker is open (REST-only mode)."""
        return self._circuit_open

    @property
    def semaphore(self) -> asyncio.Semaphore:
        """Asyncio semaphore bounding concurrent order executions."""
        return self._semaphore
