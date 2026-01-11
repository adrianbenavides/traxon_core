from __future__ import annotations

from traxon_core.persistence.db import Database
from traxon_core.persistence.db.config import DatabaseConfig
from traxon_core.persistence.db.duckdb import DuckDBConfig, DuckDbDatabase
from traxon_core.persistence.db.postgres import PostgresConfig, PostgresDatabase


def create_database(config: DatabaseConfig) -> Database:
    """
    Factory function to create a Database implementation based on configuration.
    """
    if isinstance(config, PostgresConfig):
        return PostgresDatabase(config)
    elif isinstance(config, DuckDBConfig):
        return DuckDbDatabase(config)

    raise ValueError(f"Unsupported database configuration type: {type(config)}")
