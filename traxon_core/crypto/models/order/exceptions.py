class OrderValidationError(Exception):
    """Raised when order validation fails before execution."""

    def __init__(self, symbol: str, reason: str) -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Order validation failed for {symbol}: {reason}")
