from __future__ import annotations

from typing import Union

from traxon_core.persistence.cache.disk import DiskConfig
from traxon_core.persistence.cache.redis import RedisConfig

CacheConfig = Union[RedisConfig, DiskConfig]
