import asyncio
from decimal import Decimal

import ccxt.pro as ccxt  # type: ignore[import-untyped]
from ccxt.base.types import Market  # type: ignore[import-untyped]
from ccxt.base.types import Position as CcxtPosition
from ccxt.pro import Exchange as CcxtExchange

from traxon_core.crypto.exchanges.api_patch import BaseExchangeApiPatch, ExchangeApiPatch
from traxon_core.crypto.exchanges.api_patch.bybit import BybitExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.hyperliquid import HyperliquidExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.kucoin import KucoinExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.paradex import ParadexExchangeApiPatches
from traxon_core.crypto.exchanges.api_patch.woofipro import WoofiProExchangeApiPatches
from traxon_core.crypto.exchanges.config import ExchangeConfig
from traxon_core.crypto.models import Balance, Portfolio, Position, Symbol
from traxon_core.crypto.models.account import AccountEquity
from traxon_core.crypto.models.exchange_id import ExchangeId
from traxon_core.logs.notifiers import notifier
from traxon_core.logs.structlog import logger


class Exchange:
    api: CcxtExchange
    api_patch: ExchangeApiPatch
    leverage: int
    spot_enabled: bool
    perp_enabled: bool

    def __init__(
        self,
        exchange: CcxtExchange,
        api_patch: ExchangeApiPatch,
        config: ExchangeConfig,
    ) -> None:
        self.api = exchange
        self.api_patch = api_patch
        self.api_connection = config.api_connection
        self.leverage = config.leverage
        self.spot_enabled = config.spot
        self.perp_enabled = config.perp
        self.logger = logger.bind(component=self.__class__.__name__)
        self.logger.info(
            f"{exchange.id} - initialized with spot: {self.spot_enabled}, perp: {self.perp_enabled} "
            f"and leverage: {self.leverage}"
        )

    @property
    def id(self) -> ExchangeId:
        if not self.api.id:
            raise ValueError("Exchange id is not set")
        return ExchangeId(str(self.api.id))

    @staticmethod
    async def close(exchanges: list["Exchange"]) -> None:
        for exchange in exchanges:
            try:
                await exchange.api.close()
            except Exception as e:
                logger.error(f"{exchange.id} - error closing exchange: {e}", exc_info=True)

    async def load_markets(self) -> dict[Symbol, Market]:
        max_retries = 3
        retry_delay = 5
        markets: dict[str, Market] = dict()
        for attempt in range(max_retries):
            try:
                markets = await self.api.load_markets()
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(
                        f"{self.id} - failed to load markets (attempt {attempt + 1}/{max_retries}): {str(e)}"
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    self.logger.error(
                        f"{self.id} - failed to load markets after {max_retries} attempts: {str(e)}"
                    )
                    raise

        filtered_markets = self.api_patch.filter_markets(markets)
        return filtered_markets

    def has_ws_support(self) -> bool:
        """Check if the exchange supports WebSocket order execution."""
        required_features: list[str] = ["ws", "watchOrderBook", "watchOrders"]
        for feature in required_features:
            if not self.api.has.get(feature, False):
                self.logger.debug(f"{self.id} does not support {feature}")
                return False
        return True

    async def fetch_account_equity(self) -> AccountEquity:
        """
        Returns the minimum of the available equity in perp/spot accounts.
        """
        res = await self.api.fetch_balance()
        self.logger.debug(f"{self.id} - extracting account equity from {res}")
        account_equity = self.api_patch.extract_account_equity(res)
        self.logger.info(f"{self.id} - account equity: {account_equity}")
        return account_equity

    async def fetch_available_equity_for_trading(self) -> Decimal:
        """
        Returns the minimum of the available equity in perp/spot accounts.
        """
        account_equity = await self.fetch_account_equity()
        return account_equity.minimum(self.spot_enabled, self.perp_enabled)

    async def fetch_balances(self, symbols: list[Symbol] | None = None) -> list[Balance]:
        """
        Fetches the spot balances for the exchange, optionally filtered by symbols.
        """
        balances: list[Balance] = []

        markets = await self.api.load_markets()
        res = await self.api.fetch_balance(
            {
                "type": "spot",
            }
        )
        all_balances = self.api_patch.filter_spot_balances(res)
        symbols_str = [str(s) for s in all_balances.keys() if str(s) in markets]

        if not symbols_str:
            self.logger.info(f"{self.api.id} - no spot balances found")
            return []

        self.logger.debug(f"{self.api.id} - fetching spot balances for symbols: {symbols_str}")
        tickers = await self.api.fetch_tickers(symbols_str)

        # Filter out symbols with not enough amount or value
        for symbol, amount in all_balances.items():
            if symbols is not None and symbol not in symbols:
                continue

            symbol_str = str(symbol)
            if symbol_str not in markets:
                _log = f"{self.id} - symbol {symbol} not found in markets"
                self.logger.warning(_log)
                await notifier.notify(_log)
                continue
            if symbol_str not in tickers:
                continue

            market = markets[symbol_str]
            min_amount = market["limits"]["amount"]["min"]
            min_cost = market["limits"]["cost"]["min"]
            ticker = tickers[symbol_str]
            last_price = Decimal(str(ticker["last"]))
            value = amount * last_price

            if min_amount is not None and amount < min_amount:
                continue
            if min_cost is not None and value < min_cost:
                continue

            balances.append(
                Balance(
                    market=market,
                    exchange_id=self.id,
                    symbol=symbol,
                    size=amount,
                    current_price=last_price,
                )
            )

        if balances:
            self.logger.info(f"{self.api.id} - spot balances: {balances}")
        else:
            self.logger.info(f"{self.api.id} - no spot balances found")

        return balances

    async def fetch_positions(self, symbols: list[Symbol] | None = None) -> list[Position]:
        """
        Fetches the positions for the exchange, optionally filtered by symbols.
        """
        ccxt_positions: list[CcxtPosition] = await self.api.fetch_positions()
        positions: list[Position] = []

        # For each position, fetch the last filled order and convert to domain model
        for ccxt_position in ccxt_positions:
            symbol_str = ccxt_position["symbol"]
            if symbol_str not in self.api.markets:
                _log = f"{self.id} - symbol {symbol_str} not found in markets"
                self.logger.warning(_log)
                await notifier.notify(_log)
                continue

            symbol = Symbol(symbol_str)
            if symbols is not None and symbol not in symbols:
                continue

            # Fetch the last filled order in the last 10 days
            since = self.api.milliseconds() - 10 * 24 * 60 * 60 * 1000
            limit = 10
            last_trade_timestamp = await self.api_patch.fetch_last_order_timestamp(symbol, since, limit)
            if last_trade_timestamp:
                ccxt_position["lastTradeTimestamp"] = last_trade_timestamp
                ccxt_position["lastTradeDatetime"] = self.api.iso8601(last_trade_timestamp)

            market = self.api.markets[symbol_str]
            ticker = await self.api.fetch_ticker(symbol_str)
            last = ticker.get("last", None)
            current_price = Decimal(str(last)) if last is not None else Decimal(0)

            positions.append(
                Position(
                    market=market,
                    exchange_id=self.id,
                    symbol=symbol,
                    current_price=current_price,
                    ccxt_position=ccxt_position,
                )
            )

        return positions

    async def fetch_portfolio(self, symbols: list[Symbol] | None = None) -> Portfolio:
        """
        Fetches both spot balances and perp positions for the exchange.
        """
        balances_list: list[Balance] = []
        positions_list: list[Position] = []

        if self.spot_enabled and self.perp_enabled:
            balances_list, positions_list = await asyncio.gather(
                self.fetch_balances(symbols=symbols), self.fetch_positions(symbols=symbols)
            )
        elif self.spot_enabled:
            balances_list = await self.fetch_balances(symbols=symbols)
        elif self.perp_enabled:
            positions_list = await self.fetch_positions(symbols=symbols)

        return Portfolio(
            exchange_id=self.id,
            balances=balances_list,
            perps=positions_list,
        )


class ExchangeFactory:
    @staticmethod
    async def from_config(demo: bool, exchanges_config: list[ExchangeConfig]) -> list[Exchange]:
        exchanges = list()

        if demo:
            logger.info("demo mode enabled")

        for c in exchanges_config:
            exchange_id = c.exchange_id
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class(c.credentials)

            logger.info(f"{exchange_id} - loading exchange")

            required_features = [
                "fetchPosition",
                "fetchPositions",
            ]
            for feature in required_features:
                if not hasattr(exchange, feature):
                    raise ValueError(f"{exchange_id} does not support {feature}")

            api_patch: ExchangeApiPatch
            if exchange_id == ExchangeId.BYBIT.value:
                api_patch = BybitExchangeApiPatches(exchange, c)
            elif exchange_id == ExchangeId.HYPERLIQUID.value:
                api_patch = HyperliquidExchangeApiPatches(exchange, c)
                exchange.options["slippage"] = 0.05
            elif exchange_id == ExchangeId.KUCOINFUTURES.value:
                api_patch = KucoinExchangeApiPatches(exchange, c)
            elif exchange_id == "paradex":
                credentials = c.credentials
                credentials["walletAddress"] = str(int(credentials["ethWalletAddress"], 16))
                credentials["privateKey"] = str(int(credentials["privateKey"], 16))
                exchange = exchange_class(credentials)
                api_patch = ParadexExchangeApiPatches(exchange, c)
                exchange.options["paradexAccount"] = {
                    "privateKey": credentials["privateKey"],
                    "address": c.credentials["paradexWalletAddress"],
                }
            elif exchange_id == "woofipro":
                api_patch = WoofiProExchangeApiPatches(exchange, c)
            elif exchange_id == ExchangeId.BINANCE.value:
                # Use base patch for now if specific one doesn't exist
                api_patch = BaseExchangeApiPatch(exchange, c)
            else:
                raise ValueError(f"unknown exchange id: {exchange_id}")

            if hasattr(exchange, "enableRateLimit"):
                exchange.enableRateLimit = True

            if hasattr(exchange, "enable_demo_trading"):
                exchange.enable_demo_trading(demo)
            elif hasattr(exchange, "set_sandbox_mode"):
                exchange.set_sandbox_mode(demo)

            exchange.check_required_credentials()
            max_retries = 10
            retry_delay = 2
            for attempt in range(max_retries):
                try:
                    await exchange.load_markets()
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{exchange_id} - failed to load markets (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(retry_delay)
                    else:
                        _log = f"{exchange_id} - failed to load markets after {max_retries} attempts: {e}"
                        logger.error(_log, exc_info=True)
                        await notifier.notify(_log)
                        raise
            exchanges.append(Exchange(exchange, api_patch, c))

        return exchanges
