from __future__ import annotations

from pathlib import Path

from beartype import beartype
from pydantic import BaseModel, ConfigDict, Field, field_validator


@beartype
class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    flow: str = Field(min_length=1)
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_db_path(cls, v: str) -> str:
        """Ensure parent directory exists."""
        path = Path(v).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)
