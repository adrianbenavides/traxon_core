"""
OrderRouter: groups orders by exchange, initializes sessions concurrently,
then fans out order executions concurrently via asyncio.TaskGroup.

Design:
- Stateless between route_and_collect invocations — fresh ExchangeSession per call.
- Phase 1 TaskGroup: initialize all exchange sessions concurrently.
- Phase 2 TaskGroup: execute all orders concurrently; a fatal exception in one
  task triggers structured cancellation of siblings via ExceptionGroup.
- Orphan detection: orders for unknown exchanges call pairing.notify_failed()
  before being skipped — no silent orphan.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from beartype import beartype

from traxon_core.crypto.exchanges.config import ExchangeApiConnection
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import ExchangeId
from traxon_core.crypto.models.order import OrderRequest, OrdersToExecute, OrderType
from traxon_core.crypto.order_executor.base import OrderExecutor, OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.event_bus import OrderEventBus
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.rest import RestApiOrderExecutor
from traxon_core.crypto.order_executor.session import ExchangeSession
from traxon_core.crypto.order_executor.ws import WebSocketOrderExecutor

_log = logging.getLogger(__name__)

# Type alias for the per-order execution callable injected by the host.
# Signature: (exchange, order) -> ExecutionReport | None
OrderExecuteFn = Callable[[Exchange, OrderRequest], Awaitable[ExecutionReport | None]]


class OrderRouter:
    """
    Routes orders to per-exchange sessions and fans out execution concurrently.

    Stateless between route_and_collect invocations: each call creates fresh
    ExchangeSession instances.
    """

    @beartype
    def __init__(
        self,
        config: ExecutorConfig,
        event_bus: OrderEventBus | None = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus

    def _select_executor(
        self,
        exchange: Exchange,
        session: ExchangeSession,
    ) -> OrderExecutor:
        """Select WS or REST executor based on exchange config and circuit state."""
        if (
            exchange.api_connection == ExchangeApiConnection.WEBSOCKET.value
            and exchange.has_ws_support()
            and not session.is_circuit_open()
        ):
            return WebSocketOrderExecutor(self._config, event_bus=self._event_bus)
        return RestApiOrderExecutor(self._config, event_bus=self._event_bus)

    async def _execute_one_order(
        self,
        exchange: Exchange,
        order: OrderRequest,
        session: ExchangeSession,
        execute_fn: OrderExecuteFn | None = None,
    ) -> ExecutionReport | None:
        """Execute a single order and notify pairing on outcome.

        If execute_fn is provided, delegate to it; otherwise use the internal
        executor selection logic.
        """
        symbol = order.symbol
        log_prefix = OrderExecutorBase.log_prefix(exchange, symbol, order.side)

        try:
            if execute_fn is not None:
                report = await execute_fn(exchange, order)
            else:
                executor = self._select_executor(exchange, session)
                if order.order_type == OrderType.MARKET:
                    report = await executor.execute_taker_order(exchange, order)
                else:
                    report = await executor.execute_maker_order(exchange, order)

            if report is None:
                return None

            if report.status == OrderStatus.CLOSED:
                _log.info("%s - order executed successfully", log_prefix)
                order.pairing.notify_filled()
            else:
                _log.warning("%s - order not fully executed: %s", log_prefix, report.status)

            return report

        except Exception as exc:
            _log.warning("%s - failed to execute order: %s", log_prefix, exc, exc_info=True)
            order.pairing.notify_failed()
            return None

    @beartype
    async def route_and_collect(
        self,
        exchanges: list[Exchange],
        orders: OrdersToExecute,
        event_bus: OrderEventBus | None = None,
        execute_fn: OrderExecuteFn | None = None,
    ) -> list[ExecutionReport]:
        """
        Route orders to exchange sessions and collect ExecutionReports.

        Steps:
        1. Build exchanges_by_id index.
        2. Detect orphan orders (exchange absent) -> notify_failed and skip.
        3. Group valid orders by exchange_id.
        4. Create one fresh ExchangeSession per exchange.
        5. Initialize all sessions concurrently (TaskGroup 1).
        6. Execute all orders concurrently (TaskGroup 2).
        7. Return collected ExecutionReports.

        Args:
            exchanges: Active exchange instances for this batch.
            orders: Orders to route and execute.
            event_bus: Optional event bus override (falls back to constructor value).
            execute_fn: Optional per-order execution callable. When provided,
                bypasses internal executor selection — used by DefaultOrderExecutor
                to maintain its own _execute_order patch surface.
        """
        exchanges_by_id: dict[ExchangeId, Exchange] = {
            ExchangeId(exchange.id): exchange for exchange in exchanges
        }

        all_requests: list[OrderRequest] = []
        for req_list in orders.updates.values():
            all_requests.extend(req_list)
        for req_list in orders.new.values():
            all_requests.extend(req_list)

        orders_by_exchange: dict[ExchangeId, list[OrderRequest]] = {}
        for order in all_requests:
            eid = order.exchange_id
            if eid not in exchanges_by_id:
                _log.error("exchange %s not found for order %s — skipping", eid, order.symbol)
                order.pairing.notify_failed()
                continue
            if eid not in orders_by_exchange:
                orders_by_exchange[eid] = []
            orders_by_exchange[eid].append(order)

        if not orders_by_exchange:
            return []

        effective_bus = self._event_bus or event_bus or OrderEventBus()

        sessions: dict[ExchangeId, ExchangeSession] = {
            eid: ExchangeSession(
                exchange=exchanges_by_id[eid],
                event_bus=effective_bus,
                max_concurrent_orders=self._config.max_concurrent_orders_per_exchange,
            )
            for eid in orders_by_exchange
        }

        try:
            async with asyncio.TaskGroup() as tg:
                for eid, session in sessions.items():
                    first_symbol = orders_by_exchange[eid][0].symbol
                    tg.create_task(session.initialize(first_symbol))
        except* Exception as eg:
            _log.error("errors during session initialization: %s", eg.exceptions)

        tasks: list[asyncio.Task[ExecutionReport | None]] = []

        async def _run_order(
            exchange: Exchange,
            order: OrderRequest,
            session: ExchangeSession,
        ) -> ExecutionReport | None:
            return await self._execute_one_order(exchange, order, session, execute_fn)

        try:
            async with asyncio.TaskGroup() as tg:
                for eid, order_list in orders_by_exchange.items():
                    exchange = exchanges_by_id[eid]
                    session = sessions[eid]
                    for order in order_list:
                        tasks.append(tg.create_task(_run_order(exchange, order, session)))
        except* Exception as eg:
            _log.error("errors during order execution fan-out: %s", eg.exceptions)
        else:
            results: list[ExecutionReport] = []
            for task in tasks:
                report = task.result()
                if report is not None:
                    results.append(report)
            return results

        return []
