from __future__ import annotations

from traxon_core.persistence.cache.base import Cache
from traxon_core.persistence.cache.config import CacheConfig
from traxon_core.persistence.cache.disk import DiskCache, DiskConfig
from traxon_core.persistence.cache.redis import RedisCache, RedisConfig


def create_cache(config: CacheConfig) -> Cache:
    """
    Factory function to create a Cache implementation based on configuration.
    """

    if isinstance(config, RedisConfig):
        return RedisCache(config)
    elif isinstance(config, DiskConfig):
        return DiskCache(config)

    raise ValueError(f"Unsupported cache configuration type: {type(config)}")
