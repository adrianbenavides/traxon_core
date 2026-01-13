import traxon_core


def test_public_api_exports():
    # We expect core utilities to be available directly from traxon_core
    assert hasattr(traxon_core, "dates"), "traxon_core does not export 'dates'"
    assert hasattr(traxon_core, "decimals"), "traxon_core does not export 'decimals'"
    assert hasattr(traxon_core, "floats"), "traxon_core does not export 'floats'"
    assert hasattr(traxon_core, "exchange_calendar"), "traxon_core does not export 'exchange_calendar'"
    assert hasattr(traxon_core, "errors"), "traxon_core does not export 'errors'"
