import asyncio

import pytest

from traxon_core.crypto.models.order import OrderPairing


@pytest.mark.asyncio
async def test_order_pairing_notify_filled():
    pairing = OrderPairing()
    success_event = asyncio.Event()
    failure_event = asyncio.Event()
    pairing.set_events(success_event, failure_event)

    pairing.notify_filled()
    assert success_event.is_set()
    assert not failure_event.is_set()
    assert pairing.is_pair_filled()


@pytest.mark.asyncio
async def test_order_pairing_notify_failed():
    pairing = OrderPairing()
    success_event = asyncio.Event()
    failure_event = asyncio.Event()
    pairing.set_events(success_event, failure_event)

    pairing.notify_failed()
    assert failure_event.is_set()
    assert not success_event.is_set()
    assert pairing.is_pair_failed()


@pytest.mark.asyncio
async def test_order_pairing_is_single():
    pairing = OrderPairing()
    assert pairing.is_single()

    pairing.set_events(asyncio.Event(), asyncio.Event())
    assert not pairing.is_single()
