from __future__ import annotations

from beartype import beartype

from traxon_core.logs.structlog import logger


class BaseFetcher:
    """
    Base class for data fetchers providing common utilities.
    """

    def __init__(self) -> None:
        self.logger = logger.bind(component=self.__class__.__name__)

    @beartype
    def log_fetch_start(self, context: str) -> None:
        self.logger.info(f"starting fetch: {context}")

    @beartype
    def log_fetch_end(self, context: str, count: int | None = None) -> None:
        msg = f"completed fetch: {context}"
        if count is not None:
            msg += f" (found {count} items)"
        self.logger.info(msg)
