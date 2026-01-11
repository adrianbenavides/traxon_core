from __future__ import annotations

import pickle
from typing import Any, Literal, Optional

import redis
import redis.asyncio as async_redis
from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field

from traxon_core.logs.structlog import logger
from traxon_core.persistence.cache.base import Cache


@beartype
class RedisConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["redis"] = "redis"
    host: str = Field(default="localhost", min_length=1)
    port: int = Field(default=6379, ge=1, le=65535)
    db: int = Field(default=0, ge=0)
    password: Optional[str] = None


class RedisCache(Cache):
    """Redis-based cache implementation using pickle for serialization."""

    @beartype
    def __init__(self, config: RedisConfig) -> None:
        self.config = config
        self._async_client = async_redis.Redis(
            host=config.host, port=config.port, db=config.db, password=config.password
        )
        self._sync_client = redis.Redis(
            host=config.host, port=config.port, db=config.db, password=config.password
        )

    @beartype
    async def save(self, key: str, data: Any) -> None:
        """Save data to Redis asynchronously."""
        try:
            payload = pickle.dumps(data)
            await self._async_client.set(key, payload)
        except Exception as e:
            logger.error("Failed to save to Redis", key=key, error=str(e))

    @beartype
    async def load(self, key: str) -> Any | None:
        """Load data from Redis asynchronously."""
        try:
            payload = await self._async_client.get(key)
            if payload is None:
                return None
            return pickle.loads(payload)
        except Exception as e:
            logger.error("Failed to load from Redis", key=key, error=str(e))
            return None

    @beartype
    async def delete(self, key: str) -> None:
        """Delete data from Redis asynchronously."""
        try:
            await self._async_client.delete(key)
        except Exception as e:
            logger.error("Failed to delete from Redis", key=key, error=str(e))

    @beartype
    def exists(self, key: str) -> bool:
        """Check if key exists in Redis synchronously."""
        try:
            return bool(self._sync_client.exists(key))
        except Exception as e:
            logger.error("Failed to check existence in Redis", key=key, error=str(e))
            return False
