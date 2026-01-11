import polars as pl
import pandera as pa
import pytest

from traxon_core.crypto.models.instrument import InstrumentType
from traxon_core.crypto.models.portfolio import PortfolioSchema


def test_portfolio_schema_valid() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["BTC/USDT", "ETH/USDT"],
            "side": ["long", "short"],
            "price": [50000.0, 3000.0],
            "size": [0.1, 1.0],
            "notional_size": [5000.0, 3000.0],
            "value": [5000.0, 3000.0],
            "instrument": [str(InstrumentType.SPOT), str(InstrumentType.PERP)],
        }
    )
    PortfolioSchema.validate(df)


def test_portfolio_schema_invalid_instrument() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["BTC/USDT"],
            "side": ["long"],
            "price": [50000.0],
            "size": [0.1],
            "notional_size": [5000.0],
            "value": [5000.0],
            "instrument": ["invalid"],
        }
    )
    with pytest.raises(pa.errors.SchemaError):
        PortfolioSchema.validate(df)


def test_portfolio_schema_missing_field() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["BTC/USDT"],
            # missing side
            "price": [50000.0],
            "size": [0.1],
            "notional_size": [5000.0],
            "value": [5000.0],
            "instrument": [str(InstrumentType.SPOT)],
        }
    )
    with pytest.raises(pa.errors.SchemaError):
        PortfolioSchema.validate(df)


def test_portfolio_schema_strict_violation() -> None:
    df = pl.DataFrame(
        {
            "symbol": ["BTC/USDT"],
            "side": ["long"],
            "price": [50000.0],
            "size": [0.1],
            "notional_size": [5000.0],
            "value": [5000.0],
            "instrument": [str(InstrumentType.SPOT)],
            "extra": [1],
        }
    )
    with pytest.raises(pa.errors.SchemaError):
        PortfolioSchema.validate(df)