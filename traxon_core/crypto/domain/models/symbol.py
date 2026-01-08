from ccxt.base.types import Market  # type: ignore[import-untyped]

equivalent_quotes = ["USDC", "USDT"]


class Symbol:
    """Represents a trading symbol (base, quote, settle)."""

    raw_symbol: str
    base: str
    quote: str
    settle: str | None

    def __init__(self, source: object) -> None:
        if isinstance(source, str):
            self.raw_symbol = source
        elif isinstance(source, dict):
            self.raw_symbol = source["symbol"]
        elif isinstance(source, Symbol):
            self.raw_symbol = source.raw_symbol

        parts1 = self.raw_symbol.split("/")
        base = parts1[0]
        quote_settle = parts1[1]
        parts2 = quote_settle.split(":")

        self.base = base
        self.quote = parts2[0]
        self.settle = parts2[1] if len(parts2) > 1 else None

    @staticmethod
    def from_market(market: Market) -> "Symbol":
        return Symbol(market["symbol"])

    def sanitize(self) -> str:
        """Sanitize the symbol for use in filenames."""
        return self.raw_symbol.replace("/", "").replace(":", "")

    def is_spot(self) -> bool:
        """Check if the symbol is a spot symbol (no settle currency)."""
        return self.settle is None

    def __repr__(self) -> str:
        return self.__str__()

    def __str__(self) -> str:
        return self.raw_symbol

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            other = Symbol(other)
        if not isinstance(other, Symbol):
            return False

        same_base = self.base == other.base
        same_quote = self.quote == other.quote
        same_settle = self.settle == other.settle

        return same_base and same_quote and same_settle

    def __hash__(self) -> int:
        base = self.base
        quote = self.quote
        settle = self.settle if self.settle else None
        symbol = f"{base}/{quote}"
        if settle:
            symbol = f"{symbol}:{settle}"
        return hash(symbol)


class BaseQuoteSymbol:
    """Represents a partial trading symbol (base, quote) to compare the same symbols in spot and perp markets."""

    raw_symbol: str
    base: str
    quote: str

    def __init__(self, source: object) -> None:
        if isinstance(source, str):
            self.raw_symbol = source
        elif isinstance(source, Symbol):
            self.raw_symbol = f"{source.base}/{source.quote}"
        elif isinstance(source, dict):
            self.raw_symbol = f"{source['base']}/{source['quote']}"

        parts1 = self.raw_symbol.split("/")
        base = parts1[0]
        quote_settle = parts1[1]
        parts2 = quote_settle.split(":")

        self.base = base
        self.quote = parts2[0]

    @staticmethod
    def from_market(market: Market) -> "BaseQuoteSymbol":
        return BaseQuoteSymbol(f"{market['base']}/{market['quote']}")

    @staticmethod
    def from_symbol(symbol: Symbol) -> "BaseQuoteSymbol":
        return BaseQuoteSymbol(f"{symbol.base}/{symbol.quote}")

    def __repr__(self) -> str:
        return self.__str__()

    def __str__(self) -> str:
        return f"{self.base}/{self.quote}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseQuoteSymbol):
            return False

        same_base = self.base == other.base
        same_quote = self.quote == other.quote
        equivalent_quote = self.quote in equivalent_quotes and other.quote in equivalent_quotes

        return same_base and (same_quote or equivalent_quote)

    def __hash__(self) -> int:
        base = self.base
        quote = self.quote if self.quote not in equivalent_quotes else "USDX"
        return hash(f"{base}/{quote}")
