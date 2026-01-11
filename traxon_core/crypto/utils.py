from beartype import beartype

from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models.order import OrderSide


@beartype
def log_prefix(exchange: Exchange, symbol: str, side: OrderSide | None = None) -> str:
    """
    Generate a consistent log prefix for exchange operations.

    Format: {symbol}@{exchange_id}[_{side}]
    Example: BTC/USDT@binance or BTC/USDT@bybit_buy
    """
    exchange_id: str = exchange.id
    prefix: str = f"{symbol}@{exchange_id}"
    if side:
        prefix += f"_{side.to_ccxt()}"
    return prefix
