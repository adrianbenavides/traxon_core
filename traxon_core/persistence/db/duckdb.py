from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Iterator, Literal, Optional, cast

import duckdb
import polars as pl
from _duckdb import DuckDBPyRelation
from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field, field_validator

from traxon_core.persistence.db.base import Database


@beartype
class DuckDBConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["duckdb"] = "duckdb"
    path: str = Field(min_length=1)
    read_only: bool = False

    @field_validator("path")
    @classmethod
    def validate_db_path(cls, v: str) -> str:
        """Ensure parent directory exists."""
        path = Path(v).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)


class DuckDbDatabase:
    """
    DuckDB implementation of the Database protocol.
    """

    @beartype
    def __init__(self, config: DuckDBConfig) -> None:
        self._config: Final[DuckDBConfig] = config
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

    def fetchdf(self) -> pl.DataFrame:
        """Fetch all results as a Polars DataFrame."""
        if self._last_result is not None:
            return self._last_result.pl()
        return pl.DataFrame()

    def register_temp_table(self, name: str, df: pl.DataFrame) -> None:
        """Register a Polars DataFrame as a temporary table."""
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
            if hasattr(self, "_conn"):
                self._conn.close()
        except Exception:
            pass
