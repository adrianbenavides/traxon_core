from __future__ import annotations

import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
from beartype import beartype

from traxon_core.persistence.cache import Cache


class DiskCache(Cache):
    """Disk-based cache implementation using pickle."""

    @beartype
    def __init__(self, cache_dir: str = ".cache", ignore_cache: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.ignore_cache = ignore_cache
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_full_path(self, key: str) -> str:
        """Get the full path for a key."""
        clean_key = key.replace("/", "").replace("\\", "").replace(":", "")
        return str(self.cache_dir / f"{clean_key}.pkl")

    @beartype
    async def save(self, key: str, data: Any) -> None:
        """Save data to a pickle file asynchronously."""
        file_path = self._get_full_path(key)
        binary_data = pickle.dumps(data)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(binary_data)

    @beartype
    async def load(self, key: str) -> Any | None:
        """Load data from a pickle file asynchronously."""
        if self.ignore_cache:
            return None

        file_path = self._get_full_path(key)
        if not os.path.exists(file_path):
            return None

        async with aiofiles.open(file_path, "rb") as f:
            binary_data = await f.read()
            return pickle.loads(binary_data)

    @beartype
    async def load_if_recent(self, key: str, max_age: timedelta) -> Any | None:
        """Load data if it's not older than max_age."""
        if self.ignore_cache:
            return None

        file_path = self._get_full_path(key)
        if not os.path.exists(file_path):
            return None

        modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        if datetime.now() - modified_time > max_age:
            return None

        return await self.load(key)

    @beartype
    async def delete(self, key: str) -> None:
        """Delete a pickle file."""
        file_path = self._get_full_path(key)
        if os.path.exists(file_path):
            os.remove(file_path)

    @beartype
    def exists(self, key: str) -> bool:
        """Check if a pickle file exists."""
        if self.ignore_cache:
            return False
        return os.path.exists(self._get_full_path(key))
