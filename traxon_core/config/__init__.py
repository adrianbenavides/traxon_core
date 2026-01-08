from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from beartype import beartype
from yaml import MappingNode, ScalarNode
from yaml.loader import SafeLoader


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""

    pass


class EnvVarLoader(SafeLoader):
    """YAML loader that supports environment variable interpolation."""

    def __init__(self, stream: str | bytes) -> None:
        super().__init__(stream)

    def construct_scalar(self, node: ScalarNode | MappingNode) -> str:
        value: str = super().construct_scalar(node)
        if isinstance(value, str):
            pattern: str = r"\$\{([^}^{]+)\}"
            matches = re.finditer(pattern, value)
            for match in matches:
                env_var: str = match.group(1)
                env_value: str = os.environ.get(env_var, "")
                value = value.replace(f"${{{env_var}}}", env_value)
        return value


@beartype
def load_from_yaml(path: str | Path) -> dict[str, object]:
    """
    Load a YAML config file with environment variable interpolation.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed config as a dictionary.

    Raises:
        ConfigError: If the file does not exist or YAML is invalid.
    """
    config_path: Path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data: dict[str, object] = yaml.load(f, Loader=EnvVarLoader)
        if not isinstance(data, dict):
            raise ConfigError("Config root must be a mapping (dict).")
        return data
    except yaml.YAMLError as err:
        raise ConfigError(f"YAML parsing error: {err}") from err
