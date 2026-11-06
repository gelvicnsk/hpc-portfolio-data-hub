"""Tests du chargeur générique et du chargement TOP500.

- Tests unitaires : toujours exécutés.
- Tests d'intégration : nécessitent un PostgreSQL ; ignorés si PG_TEST_DSN n'est pas défini.
  Ils n'utilisent que des tables *_test et les suppriment à la fin : sans risque pour la
  base de développement.

    PG_TEST_DSN="postgresql://hub:change_me@localhost:5432/hpc_hub" pytest tests/test_loader.py
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pytest

from pipeline.generate_portfolio import generate, write
from pipeline.ingest.load_portfolio import load_portfolio
from pipeline.ingest.load_top500 import find_top500_files, load_top500
from pipeline.ingest.loader import iter_records, load_dataframe, pg_type

FIXTURE = Path(__file__).parent / "fixtures" / "top500_sample.csv"
PG_TEST_DSN = os.getenv("PG_TEST_DSN")


# --- unitaires -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("series", "expected"),
    [
        (pd.Series([1, 2], dtype="Int64"), "bigint"),
        (pd.Series([1.5, None], dtype="Float64"), "double precision"),
        (pd.Series([True, False]), "boolean"),
        (pd.Series(pd.to_datetime(["2026-01-01"])), "timestamptz"),
        (pd.Series(["a", None], dtype="string"), "text"),
        (pd.Series(["a", 1], dtype=object), "text"),
    ],
)
def test_pg_type(series: pd.Series, expected: str) -> None:
    assert pg_type(series.dtype) == expected


def test_iter_records_converts_missing_values_to_none() -> None:
    df = pd.DataFrame(
        {
            "i": pd.Series([1, None], dtype="Int64"),
            "f": [np.float64(1.5), np.nan],
            "s": pd.Series(["x", pd.NA], dtype="string"),
        }
    )
    rows = list(iter_records(df))
    assert rows == [(1, 1.5, "x"), (None, None, None)]
    assert type(rows[0][0]) is int


def test_find_top500_files_filters_and_sorts(tmp_path: Path) -> None:
    for name in ["TOP500_202606.xlsx", "TOP500_202411.csv", "notes.txt", "other.xlsx"]:
        (tmp_path / name).write_text("x")
    assert [p.name for p in find_top500_files(tmp_path)] == [
        "TOP500_202411.csv",
        "TOP500_202606.xlsx",
    ]


def test_find_top500_files_missing_directory(tmp_path: Path) -> None:
    assert find_top500_files(tmp_path / "absent") == []


# --- intégration -------------------------------------------------------------------

integration = pytest.mark.skipif(PG_TEST_DSN is None, reason="PG_TEST_DSN non défini")

LOAD_LOG_DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS meta;
CREATE TABLE IF NOT EXISTS meta.load_log (
    load_id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, target_table TEXT NOT NULL,
    file_name TEXT, rows_loaded INTEGER, status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ, error_message TEXT
);
"""
TEST_TABLES = (
    "items_test",
    "top500_test",
    "projects_test",
    "milestones_test",
    "incidents_test",
    "costs_test",
)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    assert PG_TEST_DSN is not None
    with psycopg.connect(PG_TEST_DSN, autocommit=True) as connection:
        connection.execute(LOAD_LOG_DDL)
        for table in TEST_TABLES:
            connection.execute(f"DROP TABLE IF EXISTS raw.{table}")
        yield connection
        for table in TEST_TABLES:
            connection.execute(f"DROP TABLE IF EXISTS raw.{table}")
            connection.execute(
                "DELETE FROM meta.load_log WHERE target_table = %s", (f"raw.{table}",)
            )


def _count(conn: psycopg.Connection, query: str, params: tuple = ()) -> int:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return int(row[0])


@integration
def test_full_replace_is_idempotent(conn: psycopg.Connection) -> None:
    df = pd.DataFrame({"id": pd.Series([1, 2, 3], dtype="Int64"), "label": ["a", "b", "c"]})
    load_dataframe(conn, df, table="items_test", source="test", file_name="items.csv")
    load_dataframe(conn, df, table="items_test", source="test", file_name="items.csv")
    assert _count(conn, "SELECT count(*) FROM raw.items_test") == 3
    assert _count(conn, "SELECT count(*) FROM raw.items_test WHERE _loaded_at IS NULL") == 0


@integration
def test_new_column_is_added(conn: psycopg.Connection) -> None:
    load_dataframe(conn, pd.DataFrame({"id": [1]}), table="items_test", source="test")
    load_dataframe(
        conn, pd.DataFrame({"id": [1], "extra": ["x"]}), table="items_test", source="test"
    )
    assert _count(conn, "SELECT count(*) FROM raw.items_test WHERE extra = 'x'") == 1


@integration
def test_failed_load_is_logged_and_keeps_previous_data(conn: psycopg.Connection) -> None:
    df = pd.DataFrame({"id": [1, 2]})
    load_dataframe(conn, df, table="items_test", source="test")
    with pytest.raises(psycopg.Error):
        # colonne de partition inexistante -> erreur SQL dans la transaction
        load_dataframe(conn, df, table="items_test", source="test", replace_where={"absent": 1})
    assert _count(conn, "SELECT count(*) FROM raw.items_test") == 2
    statuses = conn.execute(
        "SELECT status FROM meta.load_log WHERE target_table = 'raw.items_test' ORDER BY load_id"
    ).fetchall()
    assert [s for (s,) in statuses] == ["success", "failed"]


@integration
def test_top500_editions_are_independent_partitions(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    shutil.copy(FIXTURE, tmp_path / "TOP500_202506.csv")
    shutil.copy(FIXTURE, tmp_path / "TOP500_202606.csv")

    assert load_top500(conn, tmp_path, table="top500_test") == {"2025-06": 8, "2026-06": 8}
    # rechargement : même état, pas de doublons
    load_top500(conn, tmp_path, table="top500_test")
    assert _count(conn, "SELECT count(*) FROM raw.top500_test") == 16

    # retirer un fichier puis recharger ne supprime pas l'édition déjà chargée
    (tmp_path / "TOP500_202506.csv").unlink()
    load_top500(conn, tmp_path, table="top500_test")
    assert _count(conn, "SELECT count(DISTINCT edition) FROM raw.top500_test") == 2


@integration
def test_load_portfolio_keeps_raw_text_and_anomalies(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    data = generate(seed=42)
    write(data, tmp_path, seed=42)
    loaded = load_portfolio(conn, tmp_path, table_suffix="_test")
    assert loaded == {name: len(df) for name, df in data.tables().items()}
    # raw ne corrige rien : doublons et coûts négatifs sont toujours là pour dbt
    assert _count(conn, "SELECT count(*) - count(DISTINCT project_id) FROM raw.projects_test") == 3
    assert _count(conn, "SELECT count(*) FROM raw.costs_test WHERE cost_eur::numeric < 0") == 4


def test_load_portfolio_requires_all_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="generate_portfolio"):
        load_portfolio(None, tmp_path)  # type: ignore[arg-type]
