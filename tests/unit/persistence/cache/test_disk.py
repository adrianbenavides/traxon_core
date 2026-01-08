
import os
import shutil
import pytest
from datetime import timedelta
from traxon_core.persistence.cache.disk import DiskCache
from traxon_core.persistence.cache import Cache


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


@pytest.mark.asyncio
async def test_disk_cache_load_if_recent(temp_cache_dir):
    """Test load_if_recent functionality."""
    cache = DiskCache(cache_dir=temp_cache_dir)
    key = "test_recent"
    data = "fresh data"
    
    await cache.save(key, data)
    
    # Should load if within max_age
    loaded = await cache.load_if_recent(key, timedelta(minutes=1))
    assert loaded == data
    
    # Should be None if max_age is zero (or very small)
    # Note: depends on file system mtime precision, but 0 should definitely fail if there's any delay
    # Or we can mock the time, but let's try a very small delta.
    loaded_expired = await cache.load_if_recent(key, timedelta(seconds=-1))
    assert loaded_expired is None
