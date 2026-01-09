from decimal import Decimal
from typing import Any

from beartype import beartype
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]

from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch
from traxon_core.crypto.exchanges.config import ExchangeConfig
from traxon_core.crypto.models import AccountEquity, Symbol


class HyperliquidExchangeApiPatches(BaseExchangeApiPatch):
    """Hyperliquid-specific API patches for account equity and trade history."""

    __slots__ = ()

    @beartype
    def __init__(self, api: CcxtExchange, config: ExchangeConfig) -> None:
        super().__init__(api, config)

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Extract account equity from Hyperliquid balance response."""
        perps_equity = Decimal(str(balances["info"]["marginSummary"]["accountValue"]))
        spot_equity = Decimal(0)  # in the balances dict, spot equity is not available
        # TODO: pass the fetch_balance() response to process it like in fetch_spot_balances()

        return AccountEquity(
            perps_equity=perps_equity,
            spot_equity=spot_equity,
            total_equity=perps_equity + spot_equity,
            available_balance=Decimal(0.0),
            maintenance_margin=Decimal(0.0),
            maintenance_margin_pct=Decimal(0.0),
        )

    @beartype
    async def fetch_last_order_timestamp(self, symbol: Symbol, since: int, limit: int) -> int | None:
        """Fetch the timestamp of the last trade for Hyperliquid."""
        timestamp = None
        trades = await self.api.fetch_trades(str(symbol), since=since, limit=limit)
        if trades:
            last_trade = max(trades, key=lambda x: x["timestamp"])
            timestamp = last_trade["timestamp"]

        return timestamp
