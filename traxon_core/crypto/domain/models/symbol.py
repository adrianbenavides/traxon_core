from dataclasses import dataclass

from ccxt.base.types import Market  # type: ignore[import-untyped]

equivalent_quotes = ["USDC", "USDT"]


@dataclass(frozen=True)
class BaseQuote:
    """Internal comparable for matching symbols across Spot and Perp."""

    base: str
    quote: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseQuote):
            return False

        # Core logic: Base must match
        if self.base != other.base:
            return False

        # Quote logic: Either exact match OR both are in the "equivalent" list (USDT/USDC)
        same_quote = self.quote == other.quote
        both_equivalent = self.quote in equivalent_quotes and other.quote in equivalent_quotes

        return same_quote or both_equivalent

    def __hash__(self) -> int:
        # Normalized hash so USDC and USDT versions produce the same key
        quote_key = "USDX" if self.quote in equivalent_quotes else self.quote
        return hash((self.base, quote_key))


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

    @property
    def base_quote(self) -> BaseQuote:
        """Returns a comparable object for cross-market matching."""
        return BaseQuote(self.base, self.quote)

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
