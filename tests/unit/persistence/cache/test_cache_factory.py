import pytest

from traxon_core.persistence.cache.disk import DiskCache, DiskConfig
from traxon_core.persistence.cache.factory import create_cache
from traxon_core.persistence.cache.redis import RedisCache, RedisConfig


def test_create_cache_redis():
    config = RedisConfig(host="localhost", port=6379)
    cache = create_cache(config)
    assert isinstance(cache, RedisCache)


def test_create_cache_disk(tmp_path):
    config = DiskConfig(path=str(tmp_path))
    cache = create_cache(config)
    assert isinstance(cache, DiskCache)


def test_create_cache_unsupported():
    with pytest.raises(ValueError, match="Unsupported cache configuration type"):
        create_cache("invalid_config")  # type: ignore
