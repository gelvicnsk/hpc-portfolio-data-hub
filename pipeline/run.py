"""Orchestration du pipeline complet, dans l'ordre :

    1. génération des données portefeuille (si absentes, ou --regenerate)
    2. chargement raw : portefeuille + TOP500
    3. dbt deps (si nécessaire) + dbt build (seeds, modèles, tests)
    4. chargement des résultats qualité dans meta.dbt_test_results
    5. export des marts en Parquet + base DuckDB

Les tests dbt en « warn » (anomalies connues) ne font pas échouer le pipeline ; une erreur
dbt, si. Les résultats qualité sont chargés dans tous les cas, pour que l'API expose aussi
les échecs.

Usage :
    python -m pipeline.run [--regenerate] [--skip-export]
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from pipeline import export_duckdb, generate_portfolio, quality
from pipeline.db import connect
from pipeline.ingest.load_portfolio import PORTFOLIO_TABLES, load_portfolio
from pipeline.ingest.load_top500 import find_top500_files, load_top500

logger = logging.getLogger("pipeline")

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "dbt"


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", ROOT / "data"))


def step(title: str) -> None:
    logger.info("=" * 8 + " %s " + "=" * 8, title)


def run_dbt(*args: str) -> int:
    command = ["dbt", *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    logger.info("$ %s", " ".join(command))
    return subprocess.run(command, cwd=DBT_DIR, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline complet du HPC Portfolio Data Hub")
    parser.add_argument("--regenerate", action="store_true", help="régénérer le portefeuille")
    parser.add_argument("--skip-export", action="store_true", help="ne pas exporter vers DuckDB")
    args = parser.parse_args(argv)
    started = time.monotonic()

    portfolio_dir = data_dir() / "raw" / "portfolio"
    top500_dir = data_dir() / "raw" / "top500"

    step("1/5 Données portefeuille")
    if args.regenerate or not all((portfolio_dir / f"{t}.csv").exists() for t in PORTFOLIO_TABLES):
        generate_portfolio.main(["--out", str(portfolio_dir)])
    else:
        logger.info("Données présentes dans %s (--regenerate pour les recréer)", portfolio_dir)

    step("2/5 Chargement raw")
    with connect() as conn:
        load_portfolio(conn, portfolio_dir)
        if find_top500_files(top500_dir):
            load_top500(conn, top500_dir)
        else:
            logger.warning("Aucun fichier TOP500 dans %s : partie TOP500 vide", top500_dir)

    step("3/5 Transformations et tests dbt")
    if not (DBT_DIR / "dbt_packages").exists() and run_dbt("deps") != 0:
        logger.error("dbt deps a échoué")
        return 1
    dbt_status = run_dbt("build")

    step("4/5 Rapport qualité")
    quality_status = quality.main(["--target-dir", str(DBT_DIR / "target")])

    if dbt_status != 0:
        logger.error("dbt build en erreur (code %d) : voir le rapport qualité", dbt_status)
        return dbt_status

    if not args.skip_export:
        step("5/5 Export analytique DuckDB")
        export_duckdb.main([])

    logger.info("Pipeline terminé en %.1f s", time.monotonic() - started)
    return quality_status


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
