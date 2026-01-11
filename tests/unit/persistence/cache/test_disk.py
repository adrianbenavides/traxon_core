import os
import shutil

import pytest

from traxon_core.persistence.cache import Cache, DiskCache


@pytest.fixture
def temp_cache_dir():
    cache_dir = ".test_cache"
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)
    os.makedirs(cache_dir)
    yield cache_dir
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)


@pytest.mark.asyncio
async def test_disk_cache_implements_protocol(temp_cache_dir):
    """Verify that DiskCache implements the Cache protocol."""
    cache = DiskCache(cache_dir=temp_cache_dir)
    assert isinstance(cache, Cache)


@pytest.mark.asyncio
async def test_disk_cache_save_load(temp_cache_dir):
    """Test saving and loading data."""
    cache = DiskCache(cache_dir=temp_cache_dir)
    key = "test_key"
    data = {"foo": "bar", "nest": [1, 2, 3]}

    await cache.save(key, data)
    loaded_data = await cache.load(key)

    assert loaded_data == data


@pytest.mark.asyncio
async def test_disk_cache_exists_delete(temp_cache_dir):
    """Test checking existence and deleting data."""
    cache = DiskCache(cache_dir=temp_cache_dir)
    key = "test_delete"
    data = "some data"

    assert not cache.exists(key)
    await cache.save(key, data)
    assert cache.exists(key)

    await cache.delete(key)
    assert not cache.exists(key)
