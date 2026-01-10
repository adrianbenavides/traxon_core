import asyncio
from datetime import timedelta
from typing import Any

from beartype import beartype

from traxon_core.logs.structlog import logger


class OrderPairing:
    """Handles logic for paired orders via composition."""

    success_event: asyncio.Event | None
    failure_event: asyncio.Event | None

    @beartype
    def __init__(self) -> None:
        self.success_event = None
        self.failure_event = None

    @beartype
    def set_events(self, success_event: asyncio.Event, failure_event: asyncio.Event) -> None:
        self.success_event = success_event
        self.failure_event = failure_event

    @beartype
    def is_single(self) -> bool:
        """Check if this order is a single order (not paired)."""
        return self.success_event is None and self.failure_event is None

    @beartype
    def notify_filled(self) -> None:
        """Signal that this order has been filled."""
        if self.success_event:
            logger.info("paired order filled - notifying")
            self.success_event.set()

    @beartype
    def notify_failed(self) -> None:
        """Signal that this order has failed execution."""
        if self.failure_event:
            logger.info("paired order failed - notifying")
            self.failure_event.set()

    @beartype
    def is_pair_filled(self) -> bool:
        """Check if the paired order has been filled."""
        return self.success_event.is_set() if self.success_event else False

    @beartype
    def is_pair_failed(self) -> bool:
        """Check if the paired order has failed."""
        return self.failure_event.is_set() if self.failure_event else False

    @beartype
    async def wait_for_pair(self, timeout: timedelta | None = None) -> tuple[bool, bool]:
        """
        Wait for the paired order to be filled or failed.
        Returns: (success, failure) tuple of booleans
        """
        if not self.success_event and not self.failure_event:
            return False, False

        tasks: list[asyncio.Task[Any]] = []
        if self.success_event:
            tasks.append(asyncio.create_task(self.success_event.wait()))
        if self.failure_event:
            tasks.append(asyncio.create_task(self.failure_event.wait()))

        try:
            if timeout:
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=timeout.total_seconds(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
            else:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
            return self.is_pair_filled(), self.is_pair_failed()
        except Exception as e:
            logger.error(f"error waiting for paired order: {e}")
            for task in tasks:
                if not task.done():
                    task.cancel()
            return False, False
