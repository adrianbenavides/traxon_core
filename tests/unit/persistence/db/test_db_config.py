import pytest
from pydantic import ValidationError


def test_postgres_config_structure():
    try:
        from traxon_core.persistence.db import DuckDBConfig, PostgresConfig
    except ImportError:
        pytest.fail("PostgresConfig and DuckDBConfig not implemented")

    # Verify strict validation for PostgresConfig
    with pytest.raises(ValidationError):
        PostgresConfig(
            host="localhost",
            port=5432,
            user="user",
            password="password",
            database="db",
            extra_field="invalid",  # Should fail
        )


def test_duckdb_config_structure():
    try:
        from traxon_core.persistence.db import DuckDBConfig
    except ImportError:
        pytest.fail("DuckDBConfig not implemented")

    # Verify strict validation for DuckDBConfig
    with pytest.raises(ValidationError):
        DuckDBConfig(
            path="/tmp/db",
            extra_field="invalid",  # Should fail
        )
