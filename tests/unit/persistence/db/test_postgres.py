from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from traxon_core.persistence.db import PostgresDatabase, PostgresConfig


@pytest.fixture
def mock_config():
    return PostgresConfig(
        host="localhost", port=5432, user="test", password="testpassword", database="testdb"
    )


@pytest.fixture
def mock_psycopg_conn():
    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        yield mock_conn


def test_postgres_database_init(mock_config, mock_psycopg_conn):
    db = PostgresDatabase(mock_config)
    assert db._config == mock_config
    assert "host=localhost" in db._conn_info
    assert "dbname=testdb" in db._conn_info


def test_postgres_database_execute(mock_config, mock_psycopg_conn):
    db = PostgresDatabase(mock_config)
    mock_cursor = MagicMock()
    mock_psycopg_conn.cursor.return_value = mock_cursor

    db.execute("SELECT 1")
    mock_cursor.execute.assert_called_once_with("SELECT 1", None)


def test_postgres_database_fetchdf(mock_config, mock_psycopg_conn):
    db = PostgresDatabase(mock_config)
    mock_cursor = MagicMock()
    mock_psycopg_conn.cursor.return_value = mock_cursor

    # Mock cursor description and fetchall
    mock_cursor.description = [MagicMock(name="id"), MagicMock(name="name")]
    mock_cursor.description[0].name = "id"
    mock_cursor.description[1].name = "name"
    mock_cursor.fetchall.return_value = [(1, "Alice"), (2, "Bob")]

    db.execute("SELECT * FROM users")
    df = db.fetchdf()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["id", "name"]


def test_postgres_database_transaction(mock_config, mock_psycopg_conn):
    db = PostgresDatabase(mock_config)

    with db.transaction():
        db.execute("UPDATE x SET y=1")

    mock_psycopg_conn.transaction.assert_called_once()
