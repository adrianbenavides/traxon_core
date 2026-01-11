from __future__ import annotations

from typing import Union

from traxon_core.persistence.cache.disk import DiskConfig
from traxon_core.persistence.cache.redis import RedisConfig
from traxon_core.persistence.db.duckdb import DuckDBConfig
from traxon_core.persistence.db.postgres import PostgresConfig

DatabaseConfig = Union[PostgresConfig, DuckDBConfig]
CacheConfig = Union[RedisConfig, DiskConfig]
