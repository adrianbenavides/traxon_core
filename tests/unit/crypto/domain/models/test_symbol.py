import pytest

from traxon_core.crypto.domain.models.symbol import BaseQuote, Symbol


def test_base_quote_equality():
    bq1 = BaseQuote("BTC", "USDT")
    bq2 = BaseQuote("BTC", "USDC")
    assert bq1 == bq2


def test_symbol_base_quote_property():
    s = Symbol("BTC/USDT:USDT")
    bq = s.base_quote
    assert bq.base == "BTC"
    assert bq.quote == "USDT"


def test_symbol_initialization():
    # From string
    s1 = Symbol("BTC/USDT")
    assert s1.base == "BTC"
    assert s1.quote == "USDT"
    assert s1.settle is None

    # From dict
    s2 = Symbol({"symbol": "ETH/USDC:USDC"})
    assert s2.base == "ETH"
    assert s2.quote == "USDC"
    assert s2.settle == "USDC"

    # From Symbol
    s3 = Symbol(s2)
    assert s3.raw_symbol == s2.raw_symbol


def test_symbol_methods():
    s = Symbol("BTC/USDT:USDT")
    assert s.sanitize() == "BTCUSDTUSDT"
    assert not s.is_spot()
    assert Symbol("BTC/USDT").is_spot()

    assert str(s) == "BTC/USDT:USDT"
    assert repr(s) == "BTC/USDT:USDT"


def test_symbol_equality_and_hash():
    s1 = Symbol("BTC/USDT")
    s2 = Symbol("BTC/USDT")
    s3 = Symbol("ETH/USDT")

    assert s1 == s2
    assert s1 != s3
    assert s1 == "BTC/USDT"
    assert s1 != 123

    assert hash(s1) == hash(s2)
    assert hash(s1) != hash(s3)


def test_base_quote_hash():
    bq1 = BaseQuote("BTC", "USDT")
    bq2 = BaseQuote("BTC", "USDC")
    bq3 = BaseQuote("ETH", "USDT")

    assert hash(bq1) == hash(bq2)
    assert hash(bq1) != hash(bq3)
