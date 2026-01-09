from decimal import Decimal
from typing import Any

from beartype import beartype
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]
from ccxt.base.types import OpenInterest  # type: ignore[import-untyped]

from traxon_core.crypto.domain.models import AccountEquity, Symbol
from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch
from traxon_core.crypto.exchanges.config import ExchangeConfig


class KucoinExchangeApiPatches(BaseExchangeApiPatch):
    """Kucoin-specific API patches for account equity, order history, and open interest."""

    __slots__ = ()

    @beartype
    def __init__(self, api: CcxtExchange, config: ExchangeConfig) -> None:
        super().__init__(api, config)

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Extract account equity from Kucoin balance response."""
        info = balances.get("info", {}).get("data", {})
        total = Decimal(str(balances.get(self.spot_quote_symbol, {}).get("total", 0)))
        available_balance = Decimal(str(info.get("availableBalance", 0)))
        margin_balance = Decimal(str(info.get("marginBalance", 0)))
        maintenance_margin_pct = Decimal(str(info.get("riskRatio", 0)))
        maintenance_margin = margin_balance * maintenance_margin_pct
        return AccountEquity(
            perps_equity=total,
            spot_equity=total,
            total_equity=total,
            available_balance=available_balance,
            maintenance_margin=maintenance_margin,
            maintenance_margin_pct=maintenance_margin_pct,
        )

    @beartype
    async def fetch_last_order_timestamp(self, symbol: Symbol, since: int, limit: int) -> int | None:
        """Fetch the timestamp of the last closed order for Kucoin."""
        timestamp = None
        orders = await self.api.fetch_closed_orders(str(symbol), since=since, limit=limit)
        if orders:
            last_order = max(orders, key=lambda x: x["timestamp"])
            timestamp = last_order["timestamp"]

        return timestamp

    @beartype
    async def fetch_open_interest(
        self, symbol: Symbol, params: dict[str, Any] | None = None
    ) -> OpenInterest | None:
        """Fetch open interest from Kucoin markets data."""
        try:
            if params is None:
                params = {}
            markets = await self.api.fetch_markets(params)
            if str(symbol) not in markets:
                return None
            market = markets[str(symbol)]
            open_interest_value: float = market.get("openInterest")
            return OpenInterest(
                symbol=str(symbol),
                openInterestValue=Decimal(str(open_interest_value)),
                openInterestAmount=None,
                baseVolume=None,
                quoteVolume=None,
                timestamp=None,
                datetime=None,
                info={},
            )
        except Exception as e:
            self.logger.error(
                f"{self.exchange_id} - error fetching open interest for {symbol}",
                error=str(e),
                exc_info=True,
            )
            return None
