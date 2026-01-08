from __future__ import annotations

from datetime import timedelta
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Protocol defining the interface for cache implementations."""

    async def save(self, key: str, data: Any) -> None:
        """Save data to the cache."""
        ...

    async def load(self, key: str) -> Any | None:
        """Load data from the cache."""
        ...

    async def load_if_recent(self, key: str, max_age: timedelta) -> Any | None:
        """Load data if it's not older than max_age."""
        ...

    async def delete(self, key: str) -> None:
        """Delete data from the cache."""
        ...

    def exists(self, key: str) -> bool:
        """Check if data exists in the cache."""
        ...
