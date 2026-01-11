from unittest.mock import patch

import pytest

from traxon_core.persistence.db.duckdb import DuckDBConfig, DuckDbDatabase
from traxon_core.persistence.db.factory import create_database
from traxon_core.persistence.db.postgres import PostgresConfig, PostgresDatabase


def test_create_database_postgres():
    config = PostgresConfig(
        host="localhost", port=5432, user="test", password="testpassword", database="testdb"
    )
    with patch("psycopg.connect") as mock_connect:
        db = create_database(config)
        assert isinstance(db, PostgresDatabase)


def test_create_database_duckdb(tmp_path):
    db_path = str(tmp_path / "test.db")
    config = DuckDBConfig(path=db_path)
    db = create_database(config)
    assert isinstance(db, DuckDbDatabase)


def test_create_database_unsupported():
    with pytest.raises(ValueError, match="Unsupported database configuration type"):
        create_database("invalid_config")  # type: ignore
