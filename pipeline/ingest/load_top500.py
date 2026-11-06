"""Charge toutes les éditions TOP500 présentes dans data/raw/top500/ vers raw.top500.

Une édition = une partition : recharger un fichier remplace uniquement les lignes de son
édition (idempotent). Sans fichier, on prévient et on sort sans erreur : la partie
portefeuille du pipeline reste utilisable sans les données TOP500.

Usage :
    python -m pipeline.ingest.load_top500
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg

from pipeline.db import connect
from pipeline.ingest.loader import load_dataframe
from pipeline.ingest.top500_parser import SUPPORTED_SUFFIXES, read_top500_file

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "top500"


def default_directory() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / "raw" / "top500"


def find_top500_files(directory: Path) -> list[Path]:
    """Fichiers TOP500 du dossier (TOP500_AAAAMM.xlsx / .xls / .csv), triés par nom."""
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_SUFFIXES
        and p.name.lower().startswith("top500")
    )


def load_top500(
    conn: psycopg.Connection, directory: Path, *, table: str = DEFAULT_TABLE
) -> dict[str, int]:
    """Charge chaque fichier et renvoie {édition: nombre de lignes}."""
    loaded: dict[str, int] = {}
    for path in find_top500_files(directory):
        df = read_top500_file(path)
        edition = str(df["edition"].iloc[0])
        if edition in loaded:
            logger.warning(
                "Édition %s présente dans plusieurs fichiers : %s la remplace", edition, path.name
            )
        loaded[edition] = load_dataframe(
            conn,
            df,
            table=table,
            source="top500",
            file_name=path.name,
            replace_where={"edition": edition},
        )
    return loaded


def main() -> int:
    directory = default_directory()
    if not find_top500_files(directory):
        logger.warning(
            "Aucun fichier TOP500 dans %s : à télécharger sur top500.org (voir README)", directory
        )
        return 0
    with connect() as conn:
        loaded = load_top500(conn, directory)
    logger.info("TOP500 chargé : %s", ", ".join(f"{e} ({n})" for e, n in sorted(loaded.items())))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
