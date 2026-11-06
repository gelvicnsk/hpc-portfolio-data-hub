"""Export des marts PostgreSQL vers Parquet + base DuckDB pour l'analyse ad hoc.

Complémentarité des deux moteurs :
- **PostgreSQL** : système de référence (transactions, droits, API, chargements concurrents).
- **DuckDB** : analytique locale sur fichiers Parquet colonnaires, sans serveur, idéale
  pour explorer vite (pivot, fenêtres, agrégats sur l'historique TOP500) sans charger la
  base de production. Les fichiers Parquet sont aussi lisibles par pandas, Spark, Power BI…

Sorties : data/analytics/<table>.parquet et data/analytics/hub.duckdb (vues sur les Parquet).

Usage :
    python -m pipeline.export_duckdb                 # export
    python -m pipeline.export_duckdb --queries analytics/queries.sql   # requêtes de démo
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.db import connect

logger = logging.getLogger(__name__)

# (schéma, table PostgreSQL) -> nom du fichier / de la vue DuckDB
EXPORTS: dict[str, tuple[str, str]] = {
    "dim_client": ("marts", "dim_client"),
    "dim_project": ("marts", "dim_project"),
    "fct_project_delivery": ("marts", "fct_project_delivery"),
    "fct_costs_monthly": ("marts", "fct_costs_monthly"),
    "fct_incidents": ("marts", "fct_incidents"),
    "fct_milestones": ("marts", "fct_milestones"),
    "mart_portfolio_kpis": ("marts", "mart_portfolio_kpis"),
    "mart_top500_vendor_share": ("marts", "mart_top500_vendor_share"),
    # niveau système, pour l'exploration fine du TOP500
    "top500_systems": ("staging", "stg_top500"),
}


def default_output_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "analytics"


# Types PostgreSQL (OID) -> types pandas, pour ne pas laisser pandas les deviner :
# un entier avec des NULL deviendrait float, une colonne entièrement NULL n'aurait pas de type.
PG_OID_TO_PANDAS: dict[int, str] = {
    16: "boolean",  # bool
    20: "Int64",  # int8 / bigint
    21: "Int64",  # int2
    23: "Int64",  # int4
    700: "float64",  # float4
    701: "float64",  # float8
    1700: "float64",  # numeric (exact en base ; double suffit pour l'analytique)
    25: "string",  # text
    1043: "string",  # varchar
}
DATE_OIDS = {1082}  # date : forcées en DATE au moment de l'écriture (voir export)
TIMESTAMP_OIDS = {1114, 1184}  # timestamp, timestamptz


def to_typed_dataframe(rows: list[tuple], columns: list[tuple[str, int]]) -> pd.DataFrame:
    """Construit le DataFrame en appliquant le type PostgreSQL de chaque colonne."""
    df = pd.DataFrame(rows, columns=[name for name, _ in columns], dtype=object)
    for name, oid in columns:
        if oid in PG_OID_TO_PANDAS:
            df[name] = df[name].astype(PG_OID_TO_PANDAS[oid])
        elif oid in TIMESTAMP_OIDS:
            df[name] = pd.to_datetime(df[name], utc=oid == 1184)
    return df


def _date_columns(columns: list[tuple[str, int]]) -> list[str]:
    return [name for name, oid in columns if oid in DATE_OIDS]


def export(output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with connect() as conn:
        for name, (schema, table) in EXPORTS.items():
            with conn.cursor() as cur:
                # noms de tables internes (EXPORTS), jamais d'entrée utilisateur
                cur.execute(f'SELECT * FROM "{schema}"."{table}"')
                columns = [(d.name, d.type_code) for d in cur.description or []]
                df = to_typed_dataframe(cur.fetchall(), columns)
            path = output_dir / f"{name}.parquet"
            # les dates restent des DATE (et non des TIMESTAMP), même quand la colonne est vide
            casts = ", ".join(f'CAST("{c}" AS DATE) AS "{c}"' for c in _date_columns(columns))
            select = f"SELECT * REPLACE ({casts}) FROM df" if casts else "SELECT * FROM df"
            tmp_path = path.with_suffix(".parquet.tmp")
            duckdb.sql(select).write_parquet(str(tmp_path))
            os.replace(tmp_path, path)  # un lecteur ne voit jamais un fichier à moitié écrit
            counts[name] = len(df)
            logger.info("%-28s %6d lignes -> %s", name, len(df), path)

    database = output_dir / "hub.duckdb"
    tmp_database = output_dir / "hub.duckdb.tmp"
    tmp_database.unlink(missing_ok=True)
    with duckdb.connect(str(tmp_database)) as con:
        con.execute(f"SET file_search_path = '{output_dir.resolve()}'")
        for name in EXPORTS:
            # nom de fichier seul : la base reste utilisable depuis l'hôte comme depuis le
            # conteneur. Les fichiers sont résolus via file_search_path (voir connect_analytics).
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{name}.parquet')"
            )
    # remplacement atomique : un notebook ou un CLI qui a ouvert hub.duckdb ne bloque pas
    # l'export (DuckDB n'autorise qu'un processus écrivain) ; il lit l'ancienne version
    # jusqu'à sa prochaine connexion
    os.replace(tmp_database, database)
    logger.info("Base DuckDB : %s (%d vues)", database, len(EXPORTS))
    return counts


def split_queries(sql_text: str) -> list[tuple[str, str]]:
    """Découpe un fichier SQL en (titre, requête). Titre = commentaire « -- name: ... »."""
    queries = []
    for block in re.split(r";\s*\n", sql_text):
        title_match = re.search(r"--\s*name:\s*(.+)", block)
        body = "\n".join(
            line for line in block.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            queries.append((title_match.group(1).strip() if title_match else "requête", body))
    return queries


def connect_analytics(output_dir: Path) -> duckdb.DuckDBPyConnection:
    """Ouvre hub.duckdb en lecture, avec le dossier des Parquet comme chemin de recherche.

    Équivalent en CLI : cd data/analytics && duckdb hub.duckdb
    """
    con = duckdb.connect(str(output_dir / "hub.duckdb"), read_only=True)
    con.execute(f"SET file_search_path = '{output_dir.resolve()}'")
    return con


def run_queries(sql_file: Path, output_dir: Path) -> None:
    with connect_analytics(output_dir) as con:
        for title, query in split_queries(sql_file.read_text(encoding="utf-8")):
            print(f"\n=== {title} ===")
            print(con.sql(query).df().to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=default_output_dir())
    parser.add_argument("--queries", type=Path, help="exécuter un fichier SQL DuckDB après export")
    parser.add_argument("--no-export", action="store_true", help="requêtes seules, sans export")
    args = parser.parse_args(argv)

    if not args.no_export:
        export(args.out)
    if args.queries:
        run_queries(args.queries, args.out)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
