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
from decimal import Decimal
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


def _decimals_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """Les NUMERIC PostgreSQL arrivent en Decimal : on les passe en float pour Parquet."""
    for col in df.columns:
        sample = df[col].dropna()
        if not sample.empty and isinstance(sample.iloc[0], Decimal):
            df[col] = df[col].astype(float)
    return df


def export(output_dir: Path) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with connect() as conn:
        for name, (schema, table) in EXPORTS.items():
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT * FROM "{schema}"."{table}"'
                )  # noms internes, pas d'entrée utilisateur
                columns = [d.name for d in cur.description or []]
                df = _decimals_to_float(pd.DataFrame(cur.fetchall(), columns=columns))
            path = output_dir / f"{name}.parquet"
            duckdb.from_df(df).write_parquet(str(path))
            counts[name] = len(df)
            logger.info("%-28s %6d lignes -> %s", name, len(df), path)

    database = output_dir / "hub.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute(f"SET file_search_path = '{output_dir.resolve()}'")
        for name in EXPORTS:
            # nom de fichier seul : la base reste utilisable depuis l'hôte comme depuis le
            # conteneur. Les fichiers sont résolus via file_search_path (voir connect_analytics).
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{name}.parquet')"
            )
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
