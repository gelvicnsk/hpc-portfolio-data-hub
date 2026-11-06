"""Connexion PostgreSQL construite à partir des variables d'environnement (aucun secret en dur)."""

from __future__ import annotations

import os

import psycopg
from psycopg.conninfo import make_conninfo


def conninfo_from_env() -> str:
    return make_conninfo(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def connect(conninfo: str | None = None, *, autocommit: bool = True) -> psycopg.Connection:
    """Autocommit par défaut : chaque chargement gère ses propres transactions explicites."""
    return psycopg.connect(conninfo or conninfo_from_env(), autocommit=autocommit)
