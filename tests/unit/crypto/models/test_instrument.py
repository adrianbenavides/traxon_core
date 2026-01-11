from traxon_core.crypto.models.instrument import InstrumentType


def test_instrument_type_members() -> None:
    assert InstrumentType.SPOT.value == "spot"
    assert InstrumentType.PERP.value == "perp"
