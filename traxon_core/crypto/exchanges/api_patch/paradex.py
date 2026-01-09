from typing import Any

from beartype import beartype
from ccxt.async_support import Exchange as CcxtExchange  # type: ignore[import-untyped]

from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch
from traxon_core.crypto.exchanges.config import ExchangeConfig
from traxon_core.crypto.models import AccountEquity


class ParadexExchangeApiPatches(BaseExchangeApiPatch):
    """Paradex-specific API patches (not yet implemented)."""

    __slots__ = ()

    @beartype
    def __init__(self, api: CcxtExchange, config: ExchangeConfig) -> None:
        super().__init__(api, config)

    @beartype
    def extract_account_equity(self, balances: dict[str, Any]) -> AccountEquity:
        """Extract account equity from Paradex balance response (not yet implemented)."""
        self.logger.info(f"{self.exchange_id} balances: {balances}")
        raise NotImplementedError(f"{self.exchange_id} extract_account_equity not yet implemented")
