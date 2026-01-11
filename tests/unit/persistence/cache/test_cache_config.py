import pytest
from pydantic import ValidationError


def test_redis_config_structure():
    # Verify these classes exist and enforce strict validation
    try:
        from traxon_core.persistence.cache import DiskConfig, RedisConfig
    except ImportError:
        pytest.fail("RedisConfig and DiskConfig not implemented")

    # Verify strict validation for RedisConfig
    with pytest.raises(ValidationError):
        RedisConfig(
            host="localhost",
            port=6379,
            db=0,
            password="password",
            extra_field="invalid",  # Should fail
        )


def test_disk_config_structure():
    try:
        from traxon_core.persistence.cache import DiskConfig
    except ImportError:
        pytest.fail("DiskConfig not implemented")

    # Verify strict validation for DiskConfig
    with pytest.raises(ValidationError):
        DiskConfig(
            path="/tmp/cache",
            serializer="json",
            extra_field="invalid",  # Should fail
        )
