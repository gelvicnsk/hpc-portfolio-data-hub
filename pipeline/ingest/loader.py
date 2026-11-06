"""Chargement idempotent d'un DataFrame dans le schéma raw, avec journal des chargements.

Principes :
- **Idempotent** : recharger le même fichier donne le même état. Deux modes :
  * remplacement complet (TRUNCATE + insert) : un fichier = une table (portefeuille) ;
  * remplacement de partition (DELETE WHERE ... + insert) : un fichier = une partie de la
    table (une édition TOP500). Les autres partitions ne sont pas touchées.
- **Atomique** : suppression et insertion dans la même transaction. En cas d'erreur,
  la table garde son état précédent.
- **Traçable** : chaque chargement écrit une ligne dans meta.load_log (running ->
  success | failed), même en cas d'échec ; chaque ligne chargée porte _loaded_at et
  _source_file.
- **Schéma évolutif** : la table est créée si besoin ; une nouvelle colonne dans la source
  est ajoutée (ALTER TABLE ADD COLUMN), jamais supprimée.
- **Rapide** : insertion par COPY plutôt que des INSERT ligne à ligne.

Le typage métier reste dans dbt (staging) : ici on ne fait que transporter.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from typing import Any

import pandas as pd
import psycopg
from psycopg import sql

logger = logging.getLogger(__name__)

RAW_SCHEMA = "raw"
TECH_COLUMNS: dict[str, str] = {
    "_loaded_at": "timestamptz NOT NULL DEFAULT now()",
    "_source_file": "text",
}


def pg_type(dtype: Any) -> str:
    """Type PostgreSQL correspondant à un dtype pandas (texte par défaut)."""
    if pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return "bigint"
    if pd.api.types.is_float_dtype(dtype):
        return "double precision"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "timestamptz"
    return "text"


def iter_records(df: pd.DataFrame) -> Iterator[tuple[Any, ...]]:
    """Lignes en types Python natifs, valeurs manquantes (NaN, NA, NaT) -> None."""
    as_objects = df.astype(object).where(df.notna(), None)
    yield from as_objects.itertuples(index=False, name=None)


def ensure_table(cur: psycopg.Cursor, df: pd.DataFrame, table: str, schema: str) -> None:
    columns = [
        sql.SQL("{} {}").format(sql.Identifier(col), sql.SQL(pg_type(dtype)))
        for col, dtype in df.dtypes.items()
    ]
    tech = [
        sql.SQL("{} {}").format(sql.Identifier(col), sql.SQL(definition))
        for col, definition in TECH_COLUMNS.items()
    ]
    cur.execute(
        sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
            sql.Identifier(schema, table), sql.SQL(", ").join(columns + tech)
        )
    )
    for col, dtype in df.dtypes.items():
        cur.execute(
            sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                sql.Identifier(schema, table), sql.Identifier(col), sql.SQL(pg_type(dtype))
            )
        )


def _log_start(conn: psycopg.Connection, source: str, target: str, file_name: str | None) -> int:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO meta.load_log (source, target_table, file_name, status)
            VALUES (%s, %s, %s, 'running')
            RETURNING load_id
            """,
            (source, target, file_name),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _log_end(
    conn: psycopg.Connection,
    load_id: int,
    *,
    status: str,
    rows: int | None = None,
    error: str | None = None,
) -> None:
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            """
            UPDATE meta.load_log
            SET status = %s, rows_loaded = %s, error_message = %s, finished_at = now()
            WHERE load_id = %s
            """,
            (status, rows, error, load_id),
        )


def load_dataframe(
    conn: psycopg.Connection,
    df: pd.DataFrame,
    *,
    table: str,
    source: str,
    file_name: str | None = None,
    replace_where: Mapping[str, Any] | None = None,
    schema: str = RAW_SCHEMA,
) -> int:
    """Charge df dans schema.table et renvoie le nombre de lignes chargées.

    replace_where=None      -> la table entière est remplacée (TRUNCATE).
    replace_where={"edition": "2026-06"} -> seules ces lignes sont remplacées.
    """
    target = f"{schema}.{table}"
    load_id = _log_start(conn, source, target, file_name)
    try:
        with conn.transaction(), conn.cursor() as cur:
            ensure_table(cur, df, table, schema)
            table_id = sql.Identifier(schema, table)
            if replace_where:
                condition = sql.SQL(" AND ").join(
                    sql.SQL("{} = {}").format(sql.Identifier(col), sql.Literal(value))
                    for col, value in replace_where.items()
                )
                cur.execute(sql.SQL("DELETE FROM {} WHERE {}").format(table_id, condition))
            else:
                cur.execute(sql.SQL("TRUNCATE {}").format(table_id))

            columns = [*df.columns, "_source_file"]
            copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
                table_id, sql.SQL(", ").join(sql.Identifier(c) for c in columns)
            )
            with cur.copy(copy_stmt) as copy:
                for record in iter_records(df):
                    copy.write_row((*record, file_name))
    except Exception as exc:
        _log_end(conn, load_id, status="failed", error=str(exc)[:2000])
        logger.error("Échec du chargement de %s (%s) : %s", target, file_name, exc)
        raise

    _log_end(conn, load_id, status="success", rows=len(df))
    logger.info("%s : %d lignes chargées depuis %s", target, len(df), file_name)
    return len(df)
