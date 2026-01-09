import sys
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class AccountEquity:
    perps_equity: Decimal | None
    spot_equity: Decimal | None
    total_equity: Decimal
    available_balance: Decimal
    maintenance_margin: Decimal
    maintenance_margin_pct: Decimal

    def minimum(
        self,
        spot_enabled: bool,
        perp_enabled: bool,
    ) -> Decimal:
        if self.perps_equity is None and self.spot_equity is None:
            return self.total_equity

        if not spot_enabled:
            return self.perps_equity if self.perps_equity is not None else Decimal(0)

        if not perp_enabled:
            return self.spot_equity if self.spot_equity is not None else Decimal(0)

        perps = self.perps_equity if self.perps_equity is not None else Decimal(sys.maxsize)
        spot = self.spot_equity if self.spot_equity is not None else Decimal(sys.maxsize)
        return min(perps, spot)
