import traxon_core


def test_public_api_exports():
    # We expect core utilities to be available directly from traxon_core
    assert hasattr(traxon_core, "dates"), "traxon_core does not export 'dates'"
    assert hasattr(traxon_core, "floats"), "traxon_core does not export 'floats'"
    assert hasattr(traxon_core, "trading_dates"), "traxon_core does not export 'trading_dates'"
