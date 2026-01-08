from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Final, Iterator, Optional, cast

import duckdb
import pandas as pd
from _duckdb import DuckDBPyRelation
from beartype import beartype

from traxon_core.persistence import Database
from traxon_core.persistence.config import DatabaseConfig


class DuckDbDatabase:
    """
    DuckDB implementation of the Database protocol.
    """

    @beartype
    def __init__(self, config: DatabaseConfig) -> None:
        self._config: Final[DatabaseConfig] = config
        self._conn = duckdb.connect(str(self._config.path))
        self._last_result: Optional[DuckDBPyRelation] = None

    def execute(self, query: str, params: list[Any] | None = None) -> Database:
        """Execute a query with optional parameters."""
        if params:
            res = self._conn.execute(query, params)
        else:
            res = self._conn.execute(query)
        self._last_result = cast(DuckDBPyRelation, res)
        return self

    def fetchone(self) -> Any | None:
        """Fetch a single result row."""
        if self._last_result is not None:
            return self._last_result.fetchone()
        return None

    def fetchdf(self) -> pd.DataFrame:
        """Fetch all results as a pandas DataFrame."""
        if self._last_result is not None:
            return self._last_result.fetchdf()
        return pd.DataFrame()

    def register_temp_table(self, name: str, df: pd.DataFrame) -> None:
        """Register a pandas DataFrame as a temporary table."""
        self._conn.register(name, df)

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """Provide a context manager for transactional operations."""
        try:
            yield self
            self.commit()
        except Exception:
            raise

    def __del__(self) -> None:
        """Ensure connection is closed on deletion."""
        try:
            self._conn.close()
        except Exception:
            pass
