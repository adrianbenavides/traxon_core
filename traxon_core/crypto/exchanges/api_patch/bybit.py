from decimal import Decimal
from typing import Any

from beartype import beartype
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]

from traxon_core.crypto.domain.models import AccountEquity, Symbol
from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch
from traxon_core.crypto.exchanges.config import ExchangeConfig


class BybitExchangeApiPatches(BaseExchangeApiPatch):
    """Bybit-specific API patches for account equity and order history."""

    __slots__ = ()

    @beartype
    def __init__(self, api: CcxtExchange, config: ExchangeConfig) -> None:
        super().__init__(api, config)

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Extract account equity from Bybit balance response."""
        res = balances.get("info", {}).get("result", {}).get("list", [])[0]
        total = Decimal(str(res["totalEquity"]))
        available_balance = Decimal(str(res["totalMarginBalance"]))
        maintenance_margin = Decimal(str(res["totalMaintenanceMargin"]))
        return AccountEquity(
            perps_equity=total,
            spot_equity=total,
            total_equity=total,
            available_balance=available_balance,
            maintenance_margin=maintenance_margin,
            maintenance_margin_pct=maintenance_margin / available_balance,
        )

    @beartype
    async def fetch_last_order_timestamp(self, symbol: Symbol, since: int, limit: int) -> int | None:
        """Fetch the timestamp of the last closed order for Bybit."""
        timestamp = None
        orders = await self.api.fetch_closed_orders(str(symbol), since=since, limit=limit)
        if orders:
            last_order = max(orders, key=lambda x: x["timestamp"])
            timestamp = last_order["timestamp"]

        return timestamp
