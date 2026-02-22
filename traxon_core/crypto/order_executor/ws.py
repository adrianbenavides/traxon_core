"""
WebSocket order executor: event-driven asyncio.wait loop with exponential backoff.

Design:
- Monitoring loop suspends only via asyncio.wait(FIRST_COMPLETED) over order-status
  and order-book and timeout coroutines — no fixed polling sleep floor.
- NetworkError triggers exponential backoff: 100ms, 200ms, 400ms, ... capped at 30s.
  Each attempt emits a ws_reconnect_attempt OrderEvent.
- After max_ws_reconnect_attempts consecutive NetworkErrors the circuit breaker opens:
  session.mark_circuit_open() is called, a ws_circuit_open event is emitted, and a
  CircuitOpenError is raised so the caller can fall back to REST.
- OrderTimeoutError delegates to base.execute_taker_fallback which emits
  order_timeout_fallback and places a REST market order.
- Staleness detection: if no WS order event arrives within ws_staleness_window_s a
  REST fetch_order is called for the open order.  A ws_staleness_fallback event is
  emitted regardless of the fetch result.  If the REST call shows CLOSED the report
  is returned immediately; otherwise WS monitoring continues.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from beartype import beartype
from ccxt.base.errors import NetworkError  # type: ignore[import-untyped]

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderRequest
from traxon_core.crypto.order_executor.base import OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.event_bus import OrderEventBus, OrderState
from traxon_core.crypto.order_executor.exceptions import (
    OrderCreationError,
    OrderExecutorError,
    OrderTimeoutError,
)
from traxon_core.crypto.order_executor.models import ElapsedSeconds, ExecutionReport, OrderStatus
from traxon_core.crypto.order_executor.rejection import RejectionClassifier, RejectionSeverity

# Exponential backoff delays for WS reconnect attempts (seconds), capped at 30s
_WS_BACKOFF_DELAYS: list[float] = [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6, 30.0]


class CircuitOpenError(OrderExecutorError):
    """Raised when the WS circuit breaker trips after too many consecutive failures."""

    def __init__(self, exchange_id: str, attempts: int) -> None:
        self.exchange_id = exchange_id
        self.attempts = attempts
        super().__init__(f"WS circuit breaker opened for {exchange_id} after {attempts} consecutive failures")


class WebSocketOrderExecutor(OrderExecutorBase):
    """
    Order executor that uses WebSockets via ccxt.pro to monitor and execute orders.

    The monitoring loop suspends via asyncio.wait(FIRST_COMPLETED) over:
      - watch_order_book(symbol): fires when order book changes
      - watch_orders(symbol): fires when order status changes
      - deadline_coro: fires when the execution deadline is reached

    On NetworkError: exponential backoff starting at 100ms, doubling, capped at 30s.
    On max_ws_reconnect_attempts exceeded: CircuitOpenError raised; session.mark_circuit_open().
    On OrderTimeoutError: delegates to execute_taker_fallback (inherited from base).
    On staleness: REST fetch_order called; ws_staleness_fallback event emitted.
    """

    @beartype
    def __init__(self, config: ExecutorConfig, event_bus: OrderEventBus | None = None) -> None:
        super().__init__(config, event_bus=event_bus)

    async def _watch_orders_with_backoff(
        self,
        exchange: Exchange,
        symbol: str,
        order_id: str,
        log_prefix: str,
        exchange_id: str,
        start_time: datetime,
        session: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Await watch_orders, retrying with exponential backoff on NetworkError.
        Each retry emits a ws_reconnect_attempt event.

        If session is provided and is_circuit_open() returns True, raises CircuitOpenError
        immediately without attempting watch_orders.

        After max_ws_reconnect_attempts consecutive failures:
          - session.mark_circuit_open() is called (if session provided)
          - ws_circuit_open event is emitted
          - CircuitOpenError is raised
        """
        if session is not None and session.is_circuit_open():
            raise CircuitOpenError(exchange_id, 0)

        max_attempts: int = self.config.max_ws_reconnect_attempts
        attempt = 0
        while True:
            try:
                return await exchange.api.watch_orders(symbol)  # type: ignore[no-any-return]
            except NetworkError as exc:
                attempt += 1
                delay_index = min(attempt - 1, len(_WS_BACKOFF_DELAYS) - 1)
                delay = _WS_BACKOFF_DELAYS[delay_index]
                delay_ms = int(delay * 1000)

                self.logger.warning(
                    f"{log_prefix} - WS NetworkError (attempt {attempt}), reconnecting in {delay_ms}ms: {exc}"
                )
                self._emit(
                    self._make_event(
                        order_id=order_id,
                        exchange_id=exchange_id,
                        symbol=symbol,
                        side="",
                        state=OrderState.MONITORING_ORDER,
                        event_name="ws_reconnect_attempt",
                        submit_time=start_time,
                        latency_ms=attempt,  # encode attempt number in latency_ms field
                    )
                )

                if max_attempts > 0 and attempt >= max_attempts:
                    self.logger.error(
                        f"{log_prefix} - WS circuit breaker opening after {attempt} consecutive failures"
                    )
                    if session is not None:
                        session.mark_circuit_open()
                    self._emit(
                        self._make_event(
                            order_id=order_id,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            side="",
                            state=OrderState.FAILED,
                            event_name="ws_circuit_open",
                            submit_time=start_time,
                            latency_ms=attempt,
                        )
                    )
                    raise CircuitOpenError(exchange_id, attempt)

                await asyncio.sleep(delay)

    @beartype
    async def execute_maker_order(
        self,
        exchange: Exchange,
        request: OrderRequest,
        session: Any = None,
    ) -> ExecutionReport | None:
        """
        Execute a maker order using WebSocket connections for real-time fill detection.

        Monitoring loop suspends via asyncio.wait(FIRST_COMPLETED):
          - watch_order_book task: fires when book changes (used to set/update price)
          - watch_orders task: fires immediately when order status changes
          - deadline task: fires when timeout is reached -> taker fallback
          - staleness task: fires after ws_staleness_window_s with no WS update

        FATAL rejections (InsufficientFunds, BadSymbol) from create_limit_order:
          - request.pairing.notify_failed() is called
          - order_failed event is emitted
          - OrderCreationError is raised without retrying

        If session is provided, passes it to _watch_orders_with_backoff for circuit
        breaker enforcement.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        exchange_id = str(exchange.api.id)
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        if not exchange.has_ws_support():
            self.logger.warning(f"{log_prefix} - WebSocket support is not available for this exchange.")
            raise OrderExecutorError(f"WebSocket not supported for {exchange.id}")

        start_time = datetime.now()
        order_id: str | None = None
        order_book_state = None
        has_book_data = False
        order_placed = False
        staleness_window = self.config.ws_staleness_window_s

        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting WebSocket maker order execution (event-driven)")

        # Create the long-lived tasks
        order_book_task: asyncio.Task[Any] = asyncio.create_task(exchange.api.watch_order_book(symbol_str))
        orders_task: asyncio.Task[Any] | None = None
        deadline_task: asyncio.Task[None] | None = None
        staleness_task: asyncio.Task[None] | None = None

        try:
            while True:
                remaining_seconds = (self.timeout_duration - (datetime.now() - start_time)).total_seconds()
                if remaining_seconds <= 0:
                    raise OrderTimeoutError(symbol_str, "maker-ws", self.timeout_duration.total_seconds())

                elapsed_seconds = ElapsedSeconds((datetime.now() - start_time).total_seconds())

                wait_tasks: set[asyncio.Task[Any]] = {order_book_task}

                if orders_task is not None:
                    wait_tasks.add(orders_task)

                if deadline_task is None or deadline_task.done():
                    deadline_task = asyncio.create_task(asyncio.sleep(remaining_seconds))
                wait_tasks.add(deadline_task)

                if order_placed and order_id is not None:
                    if staleness_task is None or staleness_task.done():
                        staleness_task = asyncio.create_task(asyncio.sleep(staleness_window))
                    wait_tasks.add(staleness_task)

                done, _pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

                if deadline_task in done:
                    raise OrderTimeoutError(symbol_str, "maker-ws", self.timeout_duration.total_seconds())

                if staleness_task is not None and staleness_task in done and order_id is not None:
                    self.logger.info(f"{log_prefix} - staleness window expired, fetching order via REST")
                    try:
                        status_dict = await exchange.api.fetch_order(order_id, symbol_str)
                        report = self._build_execution_report(status_dict, exchange_id, start_time)
                        self._emit(
                            self._make_event(
                                order_id=order_id,
                                exchange_id=exchange_id,
                                symbol=symbol_str,
                                side=side_ccxt,
                                state=OrderState.MONITORING_ORDER,
                                event_name="ws_staleness_fallback",
                                submit_time=start_time,
                            )
                        )
                        if report.status == OrderStatus.CLOSED:
                            self.logger.info(
                                f"{log_prefix} - order confirmed CLOSED via REST staleness check"
                            )
                            if deadline_task and not deadline_task.done():
                                deadline_task.cancel()
                            return report
                        staleness_task = asyncio.create_task(asyncio.sleep(staleness_window))
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - staleness REST fetch_order failed: {e}")
                        staleness_task = asyncio.create_task(asyncio.sleep(staleness_window))

                if order_book_task in done:
                    try:
                        order_book = order_book_task.result()
                        order_book_task = asyncio.create_task(exchange.api.watch_order_book(symbol_str))
                        new_state = self._analyze_order_book(
                            order_book,
                            request.side,
                            order_book_state,
                            elapsed_seconds,
                            log_prefix,
                        )
                        if new_state:
                            if float(new_state.spread_pct) > float(self.max_spread_pct):
                                self.logger.debug(
                                    f"{log_prefix} - spread too high: {new_state.spread_pct:.2%}"
                                )
                            else:
                                order_book_state = new_state
                                has_book_data = True
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - error processing order book: {e}")
                        order_book_task = asyncio.create_task(exchange.api.watch_order_book(symbol_str))

                if orders_task is not None and orders_task in done:
                    try:
                        orders: list[dict[str, Any]] = orders_task.result()
                        orders_task = asyncio.create_task(
                            self._watch_orders_with_backoff(
                                exchange,
                                symbol_str,
                                order_id or "",
                                log_prefix,
                                exchange_id,
                                start_time,
                                session,
                            )
                        )
                        if staleness_task is not None and not staleness_task.done():
                            staleness_task.cancel()
                        staleness_task = asyncio.create_task(asyncio.sleep(staleness_window))

                        for o in orders:
                            if o["id"] == order_id:
                                report = self._build_execution_report(o, exchange_id, start_time)
                                if report.status == OrderStatus.CLOSED:
                                    self.logger.info(f"{log_prefix} - order filled via WS event")
                                    if not deadline_task.done():
                                        deadline_task.cancel()
                                    return report
                                elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                                    self.logger.warning(f"{log_prefix} - order failed: {report.status}")
                                    order_id = None
                                    order_placed = False
                                    if orders_task and not orders_task.done():
                                        orders_task.cancel()
                                    orders_task = None
                                    if staleness_task and not staleness_task.done():
                                        staleness_task.cancel()
                                    staleness_task = None
                    except CircuitOpenError:
                        raise
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - error processing order update: {e}")
                        orders_task = asyncio.create_task(
                            self._watch_orders_with_backoff(
                                exchange,
                                symbol_str,
                                order_id or "",
                                log_prefix,
                                exchange_id,
                                start_time,
                                session,
                            )
                        )

                if has_book_data and not order_placed and order_book_state is not None:
                    self.logger.debug(
                        f"{log_prefix} - creating limit order at {order_book_state.best_price}, "
                        f"with size {request.amount:.6f}"
                    )
                    try:
                        params: dict[str, Any] = {}
                        order_dict = await exchange.api.create_limit_order(
                            symbol=symbol_str,
                            side=side_ccxt,
                            amount=float(request.amount),
                            price=float(order_book_state.best_price),
                            params=params,
                        )
                        order_id = str(order_dict["id"])
                        order_placed = True
                        self.logger.info(f"{log_prefix} - created limit order (id={order_id})")

                        orders_task = asyncio.create_task(
                            self._watch_orders_with_backoff(
                                exchange,
                                symbol_str,
                                order_id,
                                log_prefix,
                                exchange_id,
                                start_time,
                                session,
                            )
                        )
                        if staleness_task is not None and not staleness_task.done():
                            staleness_task.cancel()
                        staleness_task = asyncio.create_task(asyncio.sleep(staleness_window))

                    except CircuitOpenError:
                        raise
                    except Exception as e:
                        severity = RejectionClassifier.classify(e)
                        if severity == RejectionSeverity.FATAL:
                            self.logger.error(f"{log_prefix} - FATAL rejection creating limit order: {e}")
                            request.pairing.notify_failed()
                            self._emit(
                                self._make_event(
                                    order_id="unknown",
                                    exchange_id=exchange_id,
                                    symbol=symbol_str,
                                    side=side_ccxt,
                                    state=OrderState.FAILED,
                                    event_name="order_failed",
                                    submit_time=start_time,
                                )
                            )
                            raise OrderCreationError(symbol_str, "limit", f"FATAL rejection: {e}") from e
                        self.logger.warning(f"{log_prefix} - failed to create limit order: {e}")

        except OrderTimeoutError:
            self.logger.warning(f"{log_prefix} - WS maker order timed out, falling back to taker")
            return await self.execute_taker_fallback(exchange, request, "ws_timeout")
        except Exception as e:
            self.logger.error(f"{log_prefix} - error executing maker order: {e}", exc_info=True)
            raise
        finally:
            for task in [order_book_task, orders_task, deadline_task, staleness_task]:
                if task is not None and not task.done():
                    task.cancel()
            if order_id:
                await self._cancel_pending_orders(exchange, symbol_str, order_id)

    @beartype
    async def execute_taker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport | None:
        """
        Execute a taker order (market order) using WebSocket connections for real-time fill detection.

        Monitoring uses asyncio.wait(FIRST_COMPLETED) over watch_orders and deadline.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        exchange_id = str(exchange.api.id)
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        if not exchange.has_ws_support():
            self.logger.warning(f"{log_prefix} - WebSocket support is not available for this exchange.")
            raise OrderExecutorError(f"WebSocket not supported for {exchange.id}")

        start_time = datetime.now()
        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting WebSocket taker order execution")

        params: dict[str, Any] = {}
        order_dict = await exchange.api.create_market_order(
            symbol=symbol_str,
            side=side_ccxt,
            amount=float(request.amount),
            params=params,
        )
        order_id = str(order_dict["id"])

        orders_task: asyncio.Task[Any] = asyncio.create_task(
            self._watch_orders_with_backoff(
                exchange, symbol_str, order_id, log_prefix, exchange_id, start_time
            )
        )
        deadline_task: asyncio.Task[None] | None = None

        try:
            while True:
                remaining_seconds = (self.timeout_duration - (datetime.now() - start_time)).total_seconds()
                if remaining_seconds <= 0:
                    raise OrderTimeoutError(symbol_str, "taker-ws", self.timeout_duration.total_seconds())

                if deadline_task is None or deadline_task.done():
                    deadline_task = asyncio.create_task(asyncio.sleep(remaining_seconds))

                done, _pending = await asyncio.wait(
                    {orders_task, deadline_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                if deadline_task in done:
                    raise OrderTimeoutError(symbol_str, "taker-ws", self.timeout_duration.total_seconds())

                if orders_task in done:
                    orders_t: list[dict[str, Any]] = orders_task.result()
                    for o in orders_t:
                        if o["id"] == order_id:
                            report = self._build_execution_report(o, exchange_id, start_time)
                            if report.status == OrderStatus.CLOSED:
                                self.logger.info(f"{log_prefix} - taker order filled via WS event")
                                if deadline_task and not deadline_task.done():
                                    deadline_task.cancel()
                                return report
                            elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                                raise OrderCreationError(symbol_str, "market", f"Order was {report.status}")
                    orders_task = asyncio.create_task(
                        self._watch_orders_with_backoff(
                            exchange, symbol_str, order_id, log_prefix, exchange_id, start_time
                        )
                    )

        except Exception as e:
            self.logger.error(f"{log_prefix} - unexpected error executing taker order: {e}")
            raise
        finally:
            for task in [orders_task, deadline_task]:
                if task is not None and not task.done():
                    task.cancel()
            await self._cancel_pending_orders(exchange, symbol_str, order_id=None)
