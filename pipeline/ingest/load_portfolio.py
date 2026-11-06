"""Charge les 4 CSV du portefeuille dans raw.projects / milestones / incidents / costs.

Tout est chargé en texte : le typage (dates, montants) est fait dans dbt staging, ce qui
permet aussi de détecter les valeurs mal formées au lieu de les perdre au chargement.
Chaque fichier remplace entièrement sa table (idempotent).

Usage :
    python -m pipeline.ingest.load_portfolio
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg

from pipeline.db import connect
from pipeline.ingest.loader import load_dataframe

logger = logging.getLogger(__name__)

PORTFOLIO_TABLES = ("projects", "milestones", "incidents", "costs")


def default_directory() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw" / "portfolio"


def read_portfolio_csv(path: Path) -> pd.DataFrame:
    # chaînes vides -> NULL ; aucune conversion de type ici
    return pd.read_csv(path, dtype="string", keep_default_na=True)


def load_portfolio(
    conn: psycopg.Connection, directory: Path, *, table_suffix: str = ""
) -> dict[str, int]:
    missing = [t for t in PORTFOLIO_TABLES if not (directory / f"{t}.csv").exists()]
    if missing:
        raise FileNotFoundError(
            f"Fichiers absents dans {directory} : {missing} "
            "(lancer python -m pipeline.generate_portfolio)"
        )
    loaded = {}
    for table in PORTFOLIO_TABLES:
        path = directory / f"{table}.csv"
        loaded[table] = load_dataframe(
            conn,
            read_portfolio_csv(path),
            table=f"{table}{table_suffix}",
            source="portfolio",
            file_name=path.name,
        )
    return loaded


def main() -> int:
    with connect() as conn:
        loaded = load_portfolio(conn, default_directory())
    logger.info("Portefeuille chargé : %s", loaded)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
