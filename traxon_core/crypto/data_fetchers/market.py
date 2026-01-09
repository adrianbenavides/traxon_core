from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import cast

from beartype import beartype

from traxon_core.crypto.data_fetchers.base import BaseFetcher
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    ExchangeId,
    Market,
    Symbol,
)
from traxon_core.persistence.cache import Cache


class MarketFetcher(BaseFetcher):
    """Handles fetching market data for strategy execution."""

    @beartype
    def __init__(self, cache: Cache) -> None:
        super().__init__()
        self.cache = cache

    @beartype
    async def _fetch_market(self, exchange: Exchange) -> tuple[ExchangeId, list[Market]]:
        self.logger.info(f"{exchange.id} - fetching markets")

        exchange_id = exchange.id
        partial_markets: list[Market] = []

        try:
            markets = await exchange.load_markets()
            self.logger.info(f"{exchange_id} - loaded {len(markets)} markets")

            # Process up to 5 markets concurrently
            semaphore = asyncio.Semaphore(5)

            async def _process_market(idx: int, symbol: Symbol, market: dict[str, Any]) -> Market | None:
                async with semaphore:
                    self.logger.info(f"{idx}/{len(markets)} {symbol}@{exchange_id} - loading recent data")
                    self.logger.debug(f"{symbol}@{exchange_id} - market data: {market}")

                    if not market.get("active", False):
                        self.logger.debug(f"{symbol}@{exchange_id} - skipping inactive market")
                        return None

                    cache_key = f"{exchange_id}_{symbol.sanitize()}_market"
                    market_obj = await self.cache.load(cache_key)
                    if market_obj is not None:
                        self.logger.debug(f"{symbol}@{exchange_id} - cache hit")
                        return cast(Market, market_obj)

                    try:
                        # Get price history for volatility calculation
                        ohlcv = await exchange.api.fetch_ohlcv(
                            str(symbol),
                            timeframe="1d",
                            limit=365 + 1,  # "+1" because current is dropped
                        )
                        if not ohlcv:
                            self.logger.warning(f"{symbol}@{exchange_id} - no price history found")
                            return None

                        # Drop most recent candle (today's)
                        ohlcv = ohlcv[:-1]

                        close_prices = [Decimal(str(candle[4])) for candle in ohlcv]
                        volumes = [Decimal(str(candle[5])) * Decimal(str(candle[4])) for candle in ohlcv]
                        volume_average_days = 20
                        if len(volumes) < volume_average_days or not close_prices:
                            self.logger.warning(
                                f"{symbol}@{exchange_id} - price history doesn't contain enough volume data"
                            )
                            return None
                        avg_volume = sum(volumes[-volume_average_days:]) / Decimal(volume_average_days)

                        # Create Market object with collected data
                        market_obj = Market(inner=market, avg_volume=avg_volume, close_prices=close_prices)
                        await self.cache.save(cache_key, market_obj)

                        return market_obj

                    except Exception as e:
                        self.logger.warning(
                            f"{symbol}@{exchange_id} - error fetching data: {str(e)}", exc_info=True
                        )
                        return None

            # Create tasks for all markets
            tasks = []
            for i, (symbol, market) in enumerate(markets.items(), start=1):
                tasks.append(_process_market(i, symbol, market))

            # Run all tasks and gather results
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"error fetching markets data: {result}")
                    continue

                if result:
                    partial_markets.append(cast(Market, result))

            self.logger.info(f"{exchange_id} - fetched data for {len(partial_markets)} markets")

        except Exception as e:
            self.logger.warning(f"{exchange_id} - error fetching markets data: {str(e)}", exc_info=True)

        return exchange_id, partial_markets

    @beartype
    async def get_markets_by_exchange(self, exchanges: list[Exchange]) -> dict[ExchangeId, list[Market]]:
        self.logger.info("fetching markets by exchange")

        tasks = [self._fetch_market(exchange) for exchange in exchanges]
        results = await asyncio.gather(*tasks)
        markets_by_exchange = {exchange_id: markets for exchange_id, markets in results}

        return markets_by_exchange
