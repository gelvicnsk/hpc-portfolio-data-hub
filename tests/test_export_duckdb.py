"""Tests de l'export DuckDB : les types PostgreSQL doivent être conservés dans le Parquet."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from pipeline.export_duckdb import split_queries, to_typed_dataframe

# (nom, OID PostgreSQL) : int8, numeric, date, bool, text
COLUMNS = [("n", 20), ("pct", 1700), ("day", 1082), ("flag", 16), ("label", 25)]


def _parquet_types(df, tmp_path: Path) -> dict[str, str]:
    path = tmp_path / "t.parquet"
    duckdb.sql('SELECT * REPLACE (CAST("day" AS DATE) AS "day") FROM df').write_parquet(str(path))
    return {row[0]: row[1] for row in duckdb.sql(f"DESCRIBE SELECT * FROM '{path}'").fetchall()}


def test_integer_with_nulls_stays_integer(tmp_path: Path) -> None:
    df = to_typed_dataframe(
        [(1, Decimal("1.5"), date(2026, 1, 1), True, "a"), (None, None, None, None, None)],
        COLUMNS,
    )
    assert _parquet_types(df, tmp_path) == {
        "n": "BIGINT",
        "pct": "DOUBLE",
        "day": "DATE",
        "flag": "BOOLEAN",
        "label": "VARCHAR",
    }


def test_fully_null_columns_keep_a_type(tmp_path: Path) -> None:
    # cas réel : évolution des parts de marché vide quand une seule édition est chargée
    df = to_typed_dataframe([(None, None, None, None, None)] * 3, COLUMNS)
    types = _parquet_types(df, tmp_path)
    assert '"NULL"' not in types.values()
    assert types["n"] == "BIGINT"


def test_split_queries_reads_titles() -> None:
    sql = "-- name: Première\nSELECT 1;\n\n-- name: Seconde\nSELECT 2;\n"
    assert split_queries(sql) == [("Première", "SELECT 1"), ("Seconde", "SELECT 2")]
