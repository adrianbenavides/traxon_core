from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final, Literal, Optional

import pandas as pd
import psycopg
from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field

from traxon_core.persistence.db.base import Database


@beartype
class PostgresConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["postgres"] = "postgres"
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    user: str = Field(min_length=1)
    password: str = Field(min_length=1)
    database: str = Field(min_length=1)


class PostgresDatabase:
    """
    PostgreSQL implementation of the Database protocol using psycopg.
    """

    @beartype
    def __init__(self, config: PostgresConfig) -> None:
        self._config: Final[PostgresConfig] = config
        # Construct connection string
        self._conn_info = (
            f"host={config.host} port={config.port} "
            f"user={config.user} password={config.password} "
            f"dbname={config.database}"
        )
        self._conn = psycopg.connect(self._conn_info)
        self._cursor: Optional[psycopg.Cursor[Any]] = None

    def execute(self, query: str, params: list[Any] | None = None) -> Database:
        """Execute a query with optional parameters."""
        if self._cursor is None or self._cursor.closed:
            self._cursor = self._conn.cursor()

        self._cursor.execute(query, params)
        return self

    def fetchone(self) -> Any | None:
        """Fetch a single result row."""
        if self._cursor is not None:
            return self._cursor.fetchone()
        return None

    def fetchdf(self) -> pd.DataFrame:
        """Fetch all results as a pandas DataFrame."""
        if self._cursor is not None and self._cursor.description is not None:
            columns = [desc.name for desc in self._cursor.description]
            data = self._cursor.fetchall()
            return pd.DataFrame(data, columns=columns)
        return pd.DataFrame()

    def register_temp_table(self, name: str, df: pd.DataFrame) -> None:
        """
        Register a pandas DataFrame as a temporary table.
        Note: In Postgres, this typically involves creating a temp table and inserting data.
        """
        # Minimal implementation: create temp table and insert
        # For performance, this could use COPY but we'll stick to a basic version first
        columns = ", ".join([f"{col} TEXT" for col in df.columns])  # Simplified typing
        self.execute(f"CREATE TEMPORARY TABLE {name} ({columns}) ON COMMIT PRESERVE ROWS")

        # Insert data
        for _, row in df.iterrows():
            placeholders = ", ".join(["%s"] * len(row))
            self.execute(f"INSERT INTO {name} VALUES ({placeholders})", list(row))

    def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[Database]:
        """Provide a context manager for transactional operations."""
        try:
            with self._conn.transaction():
                yield self
        except Exception:
            raise

    def __del__(self) -> None:
        """Ensure connection is closed on deletion."""
        try:
            if hasattr(self, "_conn") and not self._conn.closed:
                self._conn.close()
        except Exception:
            pass
