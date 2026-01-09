from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]
from ccxt.base.types import Market, OpenInterest  # type: ignore[import-untyped]

from traxon_core.crypto.domain.models import AccountEquity, ExchangeId, Symbol
from traxon_core.crypto.exchanges.config import ExchangeConfig
from traxon_core.logs.structlog import logger


@runtime_checkable
class ExchangeApiPatch(Protocol):
    """Protocol defining exchange-specific API patches for CCXT inconsistencies."""

    api: CcxtExchange
    exchange_id: ExchangeId
    spot_quote_symbol: str
    spot: bool
    perp: bool

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Extract account equity from exchange-specific balance response."""
        ...

    @beartype
    async def fetch_last_order_timestamp(self, symbol: Symbol, since: int, limit: int) -> int | None:
        """Fetch the timestamp of the last closed order/trade for a given symbol."""
        ...

    @beartype
    def filter_spot_balances(self, balances: dict[str, Any]) -> dict[Symbol, Decimal]:
        """Filter spot balances from exchange response, excluding quote currencies."""
        ...

    @beartype
    def filter_markets(self, markets: dict[str, Market]) -> dict[Symbol, Market]:
        """Filter markets based on configured spot/perp settings and quote symbol."""
        ...

    @beartype
    async def fetch_open_interest(
        self, symbol: Symbol, params: dict[str, Any] | None = None
    ) -> OpenInterest | None:
        """Fetch open interest for a perpetual symbol."""
        ...


class BaseExchangeApiPatch:
    """Base implementation providing common functionality for exchange API patches."""

    __slots__ = ("api", "exchange_id", "spot_quote_symbol", "spot", "perp", "logger")

    @beartype
    def __init__(self, api: CcxtExchange, config: ExchangeConfig) -> None:
        self.api = api
        self.exchange_id = ExchangeId(config.exchange_id)
        self.spot_quote_symbol = config.spot_quote_symbol
        self.spot = config.spot
        self.perp = config.perp
        self.logger = logger.bind(component=self.__class__.__name__)

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Must be implemented by subclasses."""
        raise NotImplementedError(f"{self.exchange_id} must implement extract_account_equity")

    @beartype
    def filter_spot_balances(self, balances: dict[str, Any]) -> dict[Symbol, Decimal]:
        """Filter spot balances from exchange response, excluding quote currencies."""
        totals = balances.get("total", {})
        self.logger.debug(f"{self.exchange_id} - filtering spot balances from dict: {totals}")

        if len(totals.items()) == 0:
            self.logger.info(f"{self.exchange_id} - no spot balances found")
            return {}

        threshold = Decimal("0.00001")
        spot_balances = {
            Symbol(f"{coin}/{self.spot_quote_symbol}"): Decimal(str(amount))
            for coin, amount in totals.items()
            if Decimal(str(amount)) >= threshold and coin not in ["USDT", "USDC"]
        }

        self.logger.debug(f"{self.exchange_id} - spot balances filtered: {spot_balances}")

        return spot_balances

    @beartype
    def filter_markets(self, markets: dict[str, Market]) -> dict[Symbol, Market]:
        """Filter markets based on configured spot/perp settings and quote symbol."""
        filtered_markets = {}
        for symbol_str, market in markets.items():
            # Skip markets that don't match configured types
            if not ((self.spot and market["type"] == "spot") or (self.perp and market["type"] == "swap")):
                continue

            symbol = Symbol(symbol_str)

            if symbol.quote != self.spot_quote_symbol or (
                symbol.settle and symbol.settle != self.spot_quote_symbol
            ):
                continue

            filtered_markets[symbol] = market

        return filtered_markets

    @beartype
    async def fetch_last_order_timestamp(self, symbol: Symbol, since: int, limit: int) -> int | None:
        """Must be implemented by subclasses."""
        raise NotImplementedError(f"{self.exchange_id} must implement fetch_last_order_timestamp")

    @beartype
    async def fetch_open_interest(
        self, symbol: Symbol, params: dict[str, Any] | None = None
    ) -> OpenInterest | None:
        """Fetch open interest for a perpetual symbol."""
        if self.api.has["fetchOpenInterest"]:
            if params is None:
                params = {}
            open_interest = await self.api.fetch_open_interest(str(symbol), params)
        else:
            self.logger.warning(f"{self.exchange_id} - fetchOpenInterest not supported for {symbol}")
            open_interest = OpenInterest(
                symbol=str(symbol),
                openInterestValue=Decimal(str(0.0)),
                openInterestAmount=None,
                baseVolume=None,
                quoteVolume=None,
                timestamp=None,
                datetime=None,
                info={},
            )
        return open_interest
