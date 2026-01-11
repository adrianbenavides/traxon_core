from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any, Literal

import aiofiles
from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field, field_validator

from traxon_core.persistence.cache.base import Cache


@beartype
class DiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["disk"] = "disk"
    path: str = Field(min_length=1)
    serializer: Literal["json", "pickle"] = "json"

    @field_validator("path")
    @classmethod
    def validate_cache_path(cls, v: str) -> str:
        """Ensure parent directory exists."""
        path = Path(v).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)


class DiskCache(Cache):
    """Disk-based cache implementation supporting multiple serializers."""

    @beartype
    def __init__(self, config: DiskConfig) -> None:
        self.config = config
        self.cache_dir = Path(config.path)
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_full_path(self, key: str) -> str:
        """Get the full path for a key."""
        clean_key = key.replace("/", "").replace("\\", "").replace(":", "")
        ext = "pkl" if self.config.serializer == "pickle" else "json"
        return str(self.cache_dir / f"{clean_key}.{ext}")

    @beartype
    async def save(self, key: str, data: Any) -> None:
        """Save data to a file asynchronously."""
        file_path = self._get_full_path(key)
        if self.config.serializer == "pickle":
            binary_data = pickle.dumps(data)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(binary_data)
        else:
            import json

            async with aiofiles.open(file_path, "w") as f:
                await f.write(json.dumps(data))

    @beartype
    async def load(self, key: str) -> Any | None:
        """Load data from a file asynchronously."""
        file_path = self._get_full_path(key)
        if not os.path.exists(file_path):
            return None

        if self.config.serializer == "pickle":
            async with aiofiles.open(file_path, "rb") as f:
                binary_data = await f.read()
                return pickle.loads(binary_data)
        else:
            import json

            async with aiofiles.open(file_path, "r") as f:
                content = await f.read()
                return json.loads(content)

    @beartype
    async def delete(self, key: str) -> None:
        """Delete a file."""
        file_path = self._get_full_path(key)
        if os.path.exists(file_path):
            os.remove(file_path)

    @beartype
    def exists(self, key: str) -> bool:
        """Check if a file exists."""
        return os.path.exists(self._get_full_path(key))
