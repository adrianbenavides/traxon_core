from unittest.mock import Mock

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderSide
from traxon_core.crypto.utils import log_prefix


def test_log_prefix_without_side() -> None:
    exchange = Mock(spec=Exchange)
    exchange.id = "binance"
    symbol = "BTC/USDT"

    prefix = log_prefix(exchange, symbol)
    assert prefix == "BTC/USDT@binance"


def test_log_prefix_with_side() -> None:
    exchange = Mock(spec=Exchange)
    exchange.id = "bybit"
    symbol = "ETH/USDT"
    side = OrderSide.BUY

    prefix = log_prefix(exchange, symbol, side)
    assert prefix == "ETH/USDT@bybit_buy"
