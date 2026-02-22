import asyncio
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderRequest, OrderType
from traxon_core.crypto.order_executor.base import OrderExecutorBase
from traxon_core.crypto.order_executor.config import ExecutorConfig
from traxon_core.crypto.order_executor.event_bus import OrderEventBus, OrderState
from traxon_core.crypto.order_executor.exceptions import (
    OrderCreationError,
    OrderExecutorError,
)
from traxon_core.crypto.order_executor.models import (
    ElapsedSeconds,
    ExecutionReport,
    OrderBookState,
    OrderStatus,
)

# Adaptive polling thresholds
_FAST_POLL_INTERVAL = 0.2  # seconds during first 10s
_SLOW_POLL_INTERVAL = 1.0  # seconds after 10s
_FAST_POLL_WINDOW = 10.0  # seconds

# Exponential backoff delays for consecutive fetch_order failures
_FETCH_BACKOFF_DELAYS = [0.5, 1.0, 2.0, 4.0]

# Maximum attempts for create_market_order (taker outer retry loop)
_TAKER_CREATE_MAX_ATTEMPTS = 3


class _OrderState(str, Enum):
    CREATE_ORDER = "CREATE_ORDER"
    MONITORING_ORDER = "MONITORING_ORDER"
    UPDATING_ORDER = "UPDATING_ORDER"
    WAIT_UNTIL_ORDER_CANCELLED = "WAIT_UNTIL_ORDER_CANCELLED"


class RestApiOrderExecutor(OrderExecutorBase):
    """
    Order executor that uses REST API calls to place and monitor orders.
    Provides polling-based approach for exchanges that don't support WebSockets
    or as a fallback option.
    """

    @beartype
    def __init__(self, config: ExecutorConfig, event_bus: OrderEventBus | None = None) -> None:
        super().__init__(config, event_bus=event_bus)

    def check_timeout(self, start_time: datetime, symbol: str, order_type: str = "execution") -> None:
        """Override to use this module's datetime (enables mocking in tests)."""
        from traxon_core.crypto.order_executor.exceptions import OrderTimeoutError

        if datetime.now() - start_time > self.timeout_duration:
            raise OrderTimeoutError(symbol, order_type, self.timeout_duration.total_seconds())

    def _adaptive_sleep_interval(self, elapsed_seconds: float) -> float:
        """Return 0.2s for the first 10s, 1.0s thereafter."""
        return _FAST_POLL_INTERVAL if elapsed_seconds < _FAST_POLL_WINDOW else _SLOW_POLL_INTERVAL

    async def _poll_until_closed(
        self,
        exchange: Exchange,
        order_id: str,
        symbol: str,
        side_ccxt: str,
        exchange_id: str,
        start_time: datetime,
        log_prefix: str,
    ) -> ExecutionReport:
        """
        Poll fetch_order until CLOSED or REJECTED/CANCELED.
        On consecutive failures applies exponential backoff [0.5, 1.0, 2.0, 4.0]
        then propagates the error after 4 failures.
        """
        fetch_failures = 0

        while True:
            self.check_timeout(start_time, symbol, "taker-poll")
            elapsed = (datetime.now() - start_time).total_seconds()

            try:
                status_dict = await exchange.api.fetch_order(order_id, symbol)
                fetch_failures = 0
                report = self._build_execution_report(status_dict, exchange_id, start_time)

                if report.status == OrderStatus.CLOSED:
                    self.logger.info(f"{log_prefix} - taker order filled")
                    self._emit(
                        self._make_event(
                            order_id=order_id,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            side=side_ccxt,
                            state=OrderState.FILLED,
                            event_name="order_fill_complete",
                            submit_time=start_time,
                            fill_qty=report.filled,
                            fill_price=report.average_price,
                        )
                    )
                    return report

                if report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                    self._emit(
                        self._make_event(
                            order_id=order_id,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            side=side_ccxt,
                            state=OrderState.FAILED,
                            event_name="order_failed",
                            submit_time=start_time,
                        )
                    )
                    raise OrderCreationError(symbol, "market", f"Order was {report.status}")

                if report.filled > 0:
                    self._emit(
                        self._make_event(
                            order_id=order_id,
                            exchange_id=exchange_id,
                            symbol=symbol,
                            side=side_ccxt,
                            state=OrderState.PARTIALLY_FILLED,
                            event_name="order_fill_partial",
                            submit_time=start_time,
                            fill_qty=report.filled,
                            fill_price=report.average_price,
                        )
                    )

            except (OrderCreationError, OrderExecutorError):
                raise
            except Exception as e:
                fetch_failures += 1
                backoff_index = min(fetch_failures - 1, len(_FETCH_BACKOFF_DELAYS) - 1)
                backoff_delay = _FETCH_BACKOFF_DELAYS[backoff_index]
                self.logger.warning(
                    f"{log_prefix} - failed to fetch order status (attempt {fetch_failures}): {e}"
                )
                await asyncio.sleep(backoff_delay)
                if fetch_failures >= len(_FETCH_BACKOFF_DELAYS):
                    raise OrderExecutorError(
                        f"fetch_order failed {fetch_failures} consecutive times for {symbol}: {e}"
                    ) from e
                continue

            sleep_interval = self._adaptive_sleep_interval(elapsed)
            await asyncio.sleep(sleep_interval)

    @beartype
    async def _fetch_order_book_update(
        self,
        exchange: Exchange,
        symbol: str,
        request: OrderRequest,
        current_state: OrderBookState | None,
        elapsed_seconds: ElapsedSeconds,
    ) -> OrderBookState | None:
        log_prefix = self.log_prefix(exchange, symbol, request.side)

        try:
            order_book: dict[str, list[list[float]]] = await exchange.api.fetch_order_book(symbol)
        except Exception as e:
            self.logger.warning(f"{log_prefix} - error processing order book: {e}")
            return None
        return self._analyze_order_book(order_book, request.side, current_state, elapsed_seconds, log_prefix)

    @beartype
    async def execute_maker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport | None:
        """
        Execute a maker order using REST API calls.

        Tries to fill the order passively with a post-only limit order at the best price.
        After the timeout, places a market order.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        exchange_id = str(exchange.api.id)
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        start_time = datetime.now()
        order_id: str | None = None
        order_book_state: OrderBookState | None = None
        current_state: _OrderState = _OrderState.CREATE_ORDER

        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting REST API maker order execution")

        try:
            while True:
                self.check_timeout(start_time, symbol_str, "maker")
                elapsed_seconds = ElapsedSeconds((datetime.now() - start_time).total_seconds())
                sleep_interval = self._adaptive_sleep_interval(elapsed_seconds)

                if current_state == _OrderState.CREATE_ORDER:
                    new_state = await self._fetch_order_book_update(
                        exchange, symbol_str, request, order_book_state, elapsed_seconds
                    )
                    if not new_state:
                        await asyncio.sleep(sleep_interval)
                        continue

                    order_book_state = new_state

                    # Check spread
                    if order_book_state.spread_pct > self.max_spread_pct:
                        self.logger.debug(
                            f"{log_prefix} - spread too high: {order_book_state.spread_pct:.2%}"
                        )
                        await asyncio.sleep(sleep_interval)
                        continue

                    self.logger.debug(
                        f"{log_prefix} - creating limit order at {order_book_state.best_price}, "
                        f"with size {request.amount:.6f}"
                    )
                    try:
                        order_dict = await exchange.api.create_limit_order(
                            symbol=symbol_str,
                            side=side_ccxt,
                            amount=float(request.amount),
                            price=float(order_book_state.best_price),
                            params=request.params,
                        )
                        order_id = order_dict["id"]
                        self.logger.info(f"{log_prefix} - created limit order (id={order_id})")
                        self._emit(
                            self._make_event(
                                order_id=str(order_id),
                                exchange_id=exchange_id,
                                symbol=symbol_str,
                                side=side_ccxt,
                                state=OrderState.SUBMITTED,
                                event_name="order_submitted",
                                submit_time=start_time,
                            )
                        )
                        current_state = _OrderState.MONITORING_ORDER
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to create limit order: {e}")
                        await asyncio.sleep(sleep_interval)

                elif current_state == _OrderState.MONITORING_ORDER and order_id:
                    fetch_failures = 0
                    try:
                        order_status_dict = await exchange.api.fetch_order(order_id, symbol_str)
                        report = self._build_execution_report(order_status_dict, exchange_id, start_time)

                        if report.status == OrderStatus.CLOSED:
                            self.logger.info(f"{log_prefix} - order filled")
                            self._emit(
                                self._make_event(
                                    order_id=str(order_id),
                                    exchange_id=exchange_id,
                                    symbol=symbol_str,
                                    side=side_ccxt,
                                    state=OrderState.FILLED,
                                    event_name="order_fill_complete",
                                    submit_time=start_time,
                                    fill_qty=report.filled,
                                    fill_price=report.average_price,
                                )
                            )
                            return report
                        elif report.status in [OrderStatus.REJECTED, OrderStatus.CANCELED]:
                            self.logger.warning(f"{log_prefix} - order failed with status: {report.status}")
                            self._emit(
                                self._make_event(
                                    order_id=str(order_id),
                                    exchange_id=exchange_id,
                                    symbol=symbol_str,
                                    side=side_ccxt,
                                    state=OrderState.FAILED,
                                    event_name="order_failed",
                                    submit_time=start_time,
                                )
                            )
                            order_id = None
                            current_state = _OrderState.CREATE_ORDER
                            continue
                        elif report.filled > 0:
                            self._emit(
                                self._make_event(
                                    order_id=str(order_id),
                                    exchange_id=exchange_id,
                                    symbol=symbol_str,
                                    side=side_ccxt,
                                    state=OrderState.PARTIALLY_FILLED,
                                    event_name="order_fill_partial",
                                    submit_time=start_time,
                                    fill_qty=report.filled,
                                    fill_price=report.average_price,
                                )
                            )

                        # Check if price update is needed
                        new_state = await self._fetch_order_book_update(
                            exchange, symbol_str, request, order_book_state, elapsed_seconds
                        )
                        if new_state:
                            old_price = (
                                Decimal(str(order_book_state.best_price))
                                if order_book_state
                                else Decimal("0")
                            )
                            new_price = Decimal(str(new_state.best_price))
                            if self._check_should_reprice(
                                order_id=str(order_id),
                                exchange_id=exchange_id,
                                symbol=symbol_str,
                                side=side_ccxt,
                                submit_time=start_time,
                                old_price=old_price,
                                new_price=new_price,
                                elapsed_seconds=float(elapsed_seconds),
                            ):
                                order_book_state = new_state
                                current_state = _OrderState.UPDATING_ORDER

                    except Exception as e:
                        fetch_failures += 1
                        backoff_index = min(fetch_failures - 1, len(_FETCH_BACKOFF_DELAYS) - 1)
                        backoff_delay = _FETCH_BACKOFF_DELAYS[backoff_index]
                        self.logger.warning(
                            f"{log_prefix} - failed to fetch order status (attempt {fetch_failures}): {e}"
                        )
                        await asyncio.sleep(backoff_delay)
                        if fetch_failures >= len(_FETCH_BACKOFF_DELAYS):
                            raise

                elif current_state == _OrderState.UPDATING_ORDER and order_id and order_book_state:
                    try:
                        await self._cancel_pending_orders(exchange, symbol_str, order_id)
                        order_id = None
                        current_state = _OrderState.WAIT_UNTIL_ORDER_CANCELLED
                    except Exception as e:
                        self.logger.warning(f"{log_prefix} - failed to initiate update (cancel): {e}")
                        current_state = _OrderState.MONITORING_ORDER

                elif current_state == _OrderState.WAIT_UNTIL_ORDER_CANCELLED:
                    await asyncio.sleep(sleep_interval)
                    current_state = _OrderState.CREATE_ORDER

                await asyncio.sleep(sleep_interval)

        except OrderExecutorError:
            raise
        except Exception as e:
            self.logger.info(f"{log_prefix} - maker execution interrupted, switching to market order: {e}")
            await self._cancel_pending_orders(exchange, symbol_str, order_id=order_id)
            taker_request = request.model_copy(update={"order_type": OrderType.MARKET})
            return await self.execute_taker_order(exchange, taker_request)
        finally:
            await self._cancel_pending_orders(exchange, symbol_str, order_id=order_id)

    @beartype
    async def execute_taker_order(self, exchange: Exchange, request: OrderRequest) -> ExecutionReport:
        """
        Execute a taker order (market order) using REST API calls.

        Attempts to create the market order up to _TAKER_CREATE_MAX_ATTEMPTS times.
        Once an order_id is obtained, polls with exponential backoff on fetch_order
        failures: delays [0.5, 1.0, 2.0, 4.0]. After 4 consecutive failures the
        error is propagated.
        """
        self.validate_request(request)
        symbol_str = request.symbol
        side_ccxt = request.side.to_ccxt()
        exchange_id = str(exchange.api.id)
        log_prefix = self.log_prefix(exchange, symbol_str, request.side)

        start_time = datetime.now()
        await self._cancel_pending_orders(exchange, symbol_str)
        self.logger.info(f"{log_prefix} - starting REST API taker order execution")

        create_attempt = 0

        while create_attempt < _TAKER_CREATE_MAX_ATTEMPTS:
            self.check_timeout(start_time, symbol_str, "taker")
            try:
                order_dict = await exchange.api.create_market_order(
                    symbol=symbol_str,
                    side=side_ccxt,
                    amount=float(request.amount),
                    params=request.params,
                )
                order_id = str(order_dict["id"])
                self._emit(
                    self._make_event(
                        order_id=order_id,
                        exchange_id=exchange_id,
                        symbol=symbol_str,
                        side=side_ccxt,
                        state=OrderState.SUBMITTED,
                        event_name="order_submitted",
                        submit_time=start_time,
                    )
                )

                return await self._poll_until_closed(
                    exchange=exchange,
                    order_id=order_id,
                    symbol=symbol_str,
                    side_ccxt=side_ccxt,
                    exchange_id=exchange_id,
                    start_time=start_time,
                    log_prefix=log_prefix,
                )

            except (OrderCreationError, OrderExecutorError):
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
                raise
            except Exception as e:
                create_attempt += 1
                self.logger.warning(f"{log_prefix} - taker create attempt {create_attempt} failed: {e}")
                if create_attempt >= _TAKER_CREATE_MAX_ATTEMPTS:
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
                    raise OrderCreationError(symbol_str, "market", str(e))
                elapsed = (datetime.now() - start_time).total_seconds()
                await asyncio.sleep(self._adaptive_sleep_interval(elapsed))

        raise OrderExecutorError(
            f"Failed to execute taker order for {symbol_str} after {_TAKER_CREATE_MAX_ATTEMPTS} attempts"
        )
