import asyncio
import time
from collections import defaultdict
from decimal import Decimal

from beartype import beartype

from traxon_core.crypto.data_fetchers.base import BaseFetcher
from traxon_core.crypto.exchanges.exchange import Exchange
from traxon_core.crypto.models import (
    ExchangeId,
    Symbol,
)
from traxon_core.crypto.models.price import Prices


class PriceFetcher(BaseFetcher):
    """Handles fetching current prices for symbols across exchanges."""

    def __init__(self) -> None:
        super().__init__()

    @beartype
    async def fetch_price(self, exchange: Exchange, symbol: Symbol) -> Prices:
        """Fetch the current price for a single symbol on a given exchange."""
        context = f"{symbol} on {exchange.id}"
        self.log_fetch_start(context)

        markets = await exchange.load_markets()
        symbol_str = str(symbol)

        if symbol_str not in markets:
            self.logger.warning(f"market data not found for {symbol}", exchange_id=exchange.id)
            return Prices(results={exchange.id: {symbol: Decimal(0)}}, timestamp=int(time.time() * 1000))

        try:
            ticker = await exchange.api.fetch_ticker(symbol_str)
            timestamp = ticker.get("timestamp") or int(time.time() * 1000)

            if ticker and "last" in ticker and ticker["last"] is not None:
                current_price = Decimal(str(ticker["last"]))
                self.log_fetch_end(context, count=1)
                return Prices(results={exchange.id: {symbol: current_price}}, timestamp=timestamp)
            else:
                self.logger.warning("no current price found", symbol=symbol_str, exchange_id=exchange.id)
                return Prices(results={exchange.id: {symbol: Decimal(0)}}, timestamp=timestamp)
        except Exception as e:
            self.logger.error(
                f"error fetching price for {symbol}: {str(e)}",
                exchange_id=exchange.id,
                exc_info=True,
            )
            return Prices(results={exchange.id: {symbol: Decimal(0)}}, timestamp=int(time.time() * 1000))

    @beartype
    async def _fetch_prices(self, exchange: Exchange, symbols: set[Symbol]) -> Prices:
        self.logger.debug(f"fetching prices for {len(symbols)} symbols", exchange_id=exchange.id)

        exchange_id = exchange.id
        current_prices: dict[Symbol, Decimal] = defaultdict(lambda: Decimal(0))
        markets = await exchange.load_markets()
        symbols_str = [str(symbol) for symbol in symbols]

        fetch_timestamp = int(time.time() * 1000)

        try:
            tickers = {}

            self.logger.debug("fetching tickers for spot symbols", exchange_id=exchange.id)
            all_spot_symbols = [str(symbol) for symbol, market in markets.items() if market.type == "spot"]
            spot_symbols = set(symbols_str).intersection(all_spot_symbols)
            if spot_symbols:
                spot_tickers = await exchange.api.fetch_tickers(list(spot_symbols))
                if not spot_tickers:
                    self.logger.warning("no spot tickers found", exchange_id=exchange_id)
                else:
                    tickers.update(spot_tickers)

            self.logger.debug("fetching tickers for perp symbols", exchange_id=exchange.id)
            all_perp_symbols = [str(symbol) for symbol, market in markets.items() if market.type == "swap"]
            perp_symbols = set(symbols_str).intersection(all_perp_symbols)
            if perp_symbols:
                perp_tickers = await exchange.api.fetch_tickers(list(perp_symbols))
                if not perp_tickers:
                    self.logger.warning("no perp tickers found", exchange_id=exchange_id)
                else:
                    tickers.update(perp_tickers)

            # Process all tickers
            for symbol in symbols:
                symbol_str = str(symbol)
                if (
                    symbol_str in tickers
                    and "last" in tickers[symbol_str]
                    and tickers[symbol_str]["last"] is not None
                ):
                    current_price = Decimal(str(tickers[symbol_str]["last"]))
                    current_prices[symbol] = current_price
                    # Use ticker timestamp if available, otherwise use fetch timestamp
                    if "timestamp" in tickers[symbol_str] and tickers[symbol_str]["timestamp"]:
                        fetch_timestamp = max(fetch_timestamp, int(tickers[symbol_str]["timestamp"]))
                else:
                    self.logger.warning("no current price found", symbol=symbol_str, exchange_id=exchange_id)
        except Exception:
            self.logger.error("error fetching prices", exchange_id=exchange_id, exc_info=True)

        return Prices(results={exchange_id: dict(current_prices)}, timestamp=fetch_timestamp)

    @beartype
    async def fetch_prices_by_exchange(
        self,
        exchanges: list[Exchange],
        symbols_by_exchange: dict[ExchangeId, set[Symbol]],
    ) -> Prices:
        """Get current prices for multiple exchanges based on symbols map."""
        self.log_fetch_start(f"prices for {len(exchanges)} exchanges")

        exchange_map = {exchange.id: exchange for exchange in exchanges}
        tasks = [
            self._fetch_prices(exchange_map[exchange_id], symbols)
            for exchange_id, symbols in symbols_by_exchange.items()
        ]
        results = await asyncio.gather(*tasks)

        final_results = {}
        max_timestamp = 0
        for res in results:
            final_results.update(res.results)
            max_timestamp = max(max_timestamp, res.timestamp)

        fetch_time = max_timestamp if max_timestamp > 0 else int(time.time() * 1000)

        self.log_fetch_end(f"prices for {len(exchanges)} exchanges")

        return Prices(results=final_results, timestamp=fetch_time)
