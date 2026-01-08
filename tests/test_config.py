import os
from pathlib import Path

import pytest

from traxon_core.config import ConfigError, load_from_yaml


def test_load_from_yaml_success(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("key: value\nlist:\n  - 1\n  - 2", encoding="utf-8")

    data = load_from_yaml(config_file)
    assert data == {"key": "value", "list": [1, 2]}


def test_load_from_yaml_nested(tmp_path):
    config_file = tmp_path / "nested.yaml"
    config_file.write_text("outer:\n  inner: 42", encoding="utf-8")

    data = load_from_yaml(config_file)
    assert data == {"outer": {"inner": 42}}


def test_load_from_yaml_env_interpolation(tmp_path):
    os.environ["TEST_VAR"] = "test_value"
    config_file = tmp_path / "env.yaml"
    config_file.write_text("path: ${TEST_VAR}/data", encoding="utf-8")

    data = load_from_yaml(config_file)
    assert data == {"path": "test_value/data"}


def test_load_from_yaml_env_interpolation_missing(tmp_path):
    if "MISSING_VAR" in os.environ:
        del os.environ["MISSING_VAR"]
    config_file = tmp_path / "missing_env.yaml"
    config_file.write_text("path: ${MISSING_VAR}/data", encoding="utf-8")

    data = load_from_yaml(config_file)
    assert data == {"path": "/data"}


def test_load_from_yaml_not_found():
    with pytest.raises(ConfigError, match="Config file not found"):
        load_from_yaml("non_existent.yaml")


def test_load_from_yaml_invalid_yaml(tmp_path):
    config_file = tmp_path / "invalid.yaml"
    config_file.write_text("key: : value", encoding="utf-8")

    with pytest.raises(ConfigError, match="YAML parsing error"):
        load_from_yaml(config_file)


def test_load_from_yaml_not_dict(tmp_path):
    config_file = tmp_path / "not_dict.yaml"
    config_file.write_text("- item1\n- item2", encoding="utf-8")

    with pytest.raises(ConfigError, match="Config root must be a mapping"):
        load_from_yaml(config_file)
