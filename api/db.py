"""Configuration et accès base de données de l'API.

L'API se connecte avec le rôle **api_reader** (lecture seule, schémas marts et meta
uniquement — voir infra/postgres/init.sql) : même en cas de faille, elle ne peut ni
écrire ni lire les données brutes.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.repository import Repository


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "hpc_hub"
    api_db_user: str = "api_reader"
    api_db_password: str = ""
    api_page_size_default: int = 20
    api_page_size_max: int = 100

    @property
    def conninfo(self) -> str:
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=self.api_db_user,
            password=self.api_db_password,
            connect_timeout=5,
            application_name="hpc-data-hub-api",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_repository() -> Iterator[Repository]:
    """Une connexion par requête : simple et suffisant pour un outil interne de lecture."""
    with psycopg.connect(get_settings().conninfo, row_factory=dict_row) as conn:
        conn.read_only = True
        yield Repository(conn)
