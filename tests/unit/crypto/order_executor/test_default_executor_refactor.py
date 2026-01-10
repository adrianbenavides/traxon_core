import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    BaseQuote,
    ExchangeId,
    OrderExecutionType,
    OrderSide,
    OrdersToExecute,
    SizedOrderBuilder,
)
from traxon_core.crypto.models.market_info import MarketInfo
from traxon_core.crypto.order_executor.base import OrderExecutor
from traxon_core.crypto.order_executor.config import ExecutorConfig, OrderExecutionStrategy
from traxon_core.crypto.order_executor.default_executor import DefaultOrderExecutor
from traxon_core.crypto.order_executor.models import ExecutionReport, OrderStatus


@pytest.fixture
def executor_config():
    return ExecutorConfig(execution=OrderExecutionStrategy.FAST, max_spread_pct=0.01)


@pytest.fixture
def mock_exchange():
    exchange = MagicMock(spec=Exchange)
    exchange.id = ExchangeId.BYBIT
    exchange.api = MagicMock()
    exchange.api.has = {}
    exchange.has_ws_support.return_value = False
    exchange.leverage = 1
    return exchange


@pytest.fixture
def market_btc():
    ccxt_market = {
        "symbol": "BTC/USDT",
        "type": "spot",
        "active": True,
        "limits": {"amount": {"min": 0.001}, "cost": {"min": 5.0}},
        "contractSize": 1.0,
        "precision": {"amount": 8, "price": 2},
    }
    return MarketInfo.from_ccxt(ccxt_market)


@pytest.mark.asyncio
async def test_default_executor_executes_request_and_notifies(executor_config, mock_exchange, market_btc):
    executor = DefaultOrderExecutor(executor_config)

    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    # Set events for pairing to work
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())

    ote = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder]})

    report = ExecutionReport(
        id="123",
        symbol="BTC/USDT",
        status=OrderStatus.CLOSED,
        amount=Decimal("0.1"),
        filled=Decimal("0.1"),
        remaining=Decimal("0"),
        timestamp=123456789,
    )

    mock_api_executor = MagicMock(spec=OrderExecutor)
    mock_api_executor.execute_taker_order = AsyncMock(return_value=report)

    with patch.object(DefaultOrderExecutor, "_select_executor", return_value=mock_api_executor):
        reports = await executor.execute_orders([mock_exchange], ote)

        assert len(reports) == 1
        assert reports[0].status == OrderStatus.CLOSED
        assert builder.pairing.is_pair_filled()


@pytest.mark.asyncio
async def test_default_executor_handles_failure_and_notifies(executor_config, mock_exchange, market_btc):
    executor = DefaultOrderExecutor(executor_config)

    builder = SizedOrderBuilder(
        exchange_id=ExchangeId.BYBIT,
        market=market_btc,
        execution_type=OrderExecutionType.TAKER,
        side=OrderSide.BUY,
        size=Decimal("0.1"),
    )
    # Set events for pairing to work
    builder.pairing.set_events(asyncio.Event(), asyncio.Event())

    ote = OrdersToExecute(updates={}, new={BaseQuote("BTC", "USDT"): [builder]})

    mock_api_executor = MagicMock(spec=OrderExecutor)
    mock_api_executor.execute_taker_order = AsyncMock(side_effect=Exception("Execution failed"))

    with patch.object(DefaultOrderExecutor, "_select_executor", return_value=mock_api_executor):
        reports = await executor.execute_orders([mock_exchange], ote)

        assert len(reports) == 0
        assert builder.pairing.is_pair_failed()
