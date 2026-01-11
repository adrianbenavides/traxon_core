from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol, runtime_checkable

import polars as pl


@runtime_checkable
class Database(Protocol):
    """
    Protocol for database operations to decouple repositories from specific backends.
    """

    def execute(self, query: str, params: list[Any] | None = None) -> Database:
        """Execute a query with optional parameters."""
        ...

    def fetchone(self) -> Any | None:
        """Fetch a single result row."""
        ...

    def fetchdf(self) -> pl.DataFrame:
        """Fetch all results as a Polars DataFrame."""
        ...

    def register_temp_table(self, name: str, df: pl.DataFrame) -> None:
        """Register a Polars DataFrame as a temporary table."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """Provide a context manager for transactional operations."""
        ...
