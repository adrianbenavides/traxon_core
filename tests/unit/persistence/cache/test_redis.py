from unittest.mock import MagicMock, patch

import fakeredis
import pytest
from pydantic import ValidationError

from traxon_core.persistence.cache.redis import RedisCache, RedisConfig


@pytest.fixture
def redis_config():
    return RedisConfig(host="localhost", port=6379, db=0)


@pytest.fixture
def fake_redis_server():
    server = fakeredis.FakeServer()
    yield server


@pytest.mark.asyncio
async def test_redis_cache_save_load(redis_config, fake_redis_server):
    """Test saving and loading from RedisCache."""
    with patch("redis.asyncio.Redis", return_value=fakeredis.FakeAsyncRedis(server=fake_redis_server)):
        with patch("redis.Redis", return_value=fakeredis.FakeRedis(server=fake_redis_server)):
            cache = RedisCache(redis_config)
            key = "key1"
            data = {"a": 1}

            await cache.save(key, data)
            loaded = await cache.load(key)
            assert loaded == data


@pytest.mark.asyncio
async def test_redis_cache_exists_delete(redis_config, fake_redis_server):
    """Test exists (sync) and delete (async)."""
    with patch("redis.asyncio.Redis", return_value=fakeredis.FakeAsyncRedis(server=fake_redis_server)):
        with patch("redis.Redis", return_value=fakeredis.FakeRedis(server=fake_redis_server)):
            cache = RedisCache(redis_config)
            key = "key2"

            assert not cache.exists(key)
            await cache.save(key, "data")
            assert cache.exists(key)

            await cache.delete(key)
            assert not cache.exists(key)


@pytest.mark.asyncio
async def test_redis_cache_graceful_degradation(redis_config):
    """Test behavior when Redis is unavailable."""
    mock_async_client = MagicMock()
    # Mocking connection error on get
    mock_async_client.get.side_effect = Exception("Connection Refused")

    with patch("redis.asyncio.Redis", return_value=mock_async_client):
        with patch("redis.Redis"):
            cache = RedisCache(redis_config)
            # Should not raise exception, but return None and log
            res = await cache.load("any")
            assert res is None


def test_redis_config_valid():
    """Test valid Redis configuration."""
    config = RedisConfig(host="localhost", port=6379, db=0)
    assert config.host == "localhost"
    assert config.port == 6379
    assert config.db == 0
    assert config.password is None


def test_redis_config_with_password():
    """Test Redis configuration with password."""
    config = RedisConfig(host="localhost", port=6379, db=0, password="secret")
    assert config.password == "secret"


def test_redis_config_defaults():
    """Test Redis configuration default values."""
    config = RedisConfig(db=0)
    assert config.host == "localhost"
    assert config.port == 6379
    assert config.db == 0


def test_redis_config_validation_missing_fields():
    """Test missing required fields raises ValidationError."""
    with pytest.raises(ValidationError):
        RedisConfig()  # type: ignore[call-arg] # Missing db


def test_redis_config_validation_types():
    """Test invalid types raise ValidationError."""
    with pytest.raises(ValidationError):
        RedisConfig(host="localhost", port="invalid_port", db=0)

    with pytest.raises(ValidationError):
        RedisConfig(host="localhost", port=6379, db="invalid_db")
