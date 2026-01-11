from typing import Any

import polars as pl

from traxon_core.persistence.db.base import Database


def test_database_protocol_signatures():
    # This is a static analysis/type checking test mostly,
    # but we can verify it at runtime if we use a mock that claims to implement it.
    class MockDB:
        def execute(self, query: str, params: list[Any] | None = None) -> "MockDB":
            return self

        def fetchone(self) -> Any | None:
            return None

        def fetchdf(self) -> pl.DataFrame:
            return pl.DataFrame()

        def register_temp_table(self, name: str, df: pl.DataFrame) -> None:
            pass

        def commit(self) -> None:
            pass

        def transaction(self):
            pass

    db: Database = MockDB()
    assert isinstance(db, Database)
