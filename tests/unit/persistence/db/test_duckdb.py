from pathlib import Path

import polars as pl
import pytest

from traxon_core.persistence.db import DuckDBConfig, DuckDbDatabase


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def config(db_path):
    return DuckDBConfig(path=db_path)


def test_duckdb_database_init(config):
    db = DuckDbDatabase(config)
    assert db._config == config
    assert Path(config.path).exists()


def test_duckdb_database_execute_fetchdf(config):
    db = DuckDbDatabase(config)
    db.execute("CREATE TABLE users (id INTEGER, name VARCHAR)")
    db.execute("INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob')")

    db.execute("SELECT * FROM users")
    df = db.fetchdf()

    assert isinstance(df, pl.DataFrame)
    assert len(df) == 2
    assert df.columns == ["id", "name"]


def test_duckdb_database_register_temp_table(config):
    db = DuckDbDatabase(config)
    df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})

    db.register_temp_table("temp_table", df)

    db.execute("SELECT * FROM temp_table")
    fetched_df = db.fetchdf()

    assert fetched_df.equals(df)
