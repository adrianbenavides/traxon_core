from __future__ import annotations

from typing import Union

from persistence.db.duckdb import DuckDBConfig
from persistence.db.postgres import PostgresConfig

DatabaseConfig = Union[PostgresConfig, DuckDBConfig]


CacheConfig = Union[RedisConfig, DiskConfig]
