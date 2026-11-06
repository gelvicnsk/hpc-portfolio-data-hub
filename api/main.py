"""API en lecture seule du HPC Portfolio Data Hub.

Lancer en local :   uvicorn api.main:app --reload
Documentation :     http://localhost:8000/docs (Swagger) — http://localhost:8000/redoc
"""

from __future__ import annotations

import logging
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from api.db import get_repository
from api.repository import Repository
from api.routers import kpis, projects, quality, top500

logger = logging.getLogger(__name__)

app = FastAPI(
    title="HPC Portfolio Data Hub",
    version="1.0.0",
    description=(
        "API en lecture seule sur les marts du Data Hub : KPI du portefeuille de "
        "supercalculateurs, détail des projets, parts de marché TOP500 et qualité des données.\n\n"
        "Connexion base avec le rôle `api_reader` (SELECT sur `marts` et `meta` uniquement)."
    ),
)

app.include_router(kpis.router)
app.include_router(projects.router)
app.include_router(top500.router)
app.include_router(quality.router)


@app.exception_handler(psycopg.OperationalError)
async def database_unavailable(_: Request, exc: psycopg.OperationalError) -> JSONResponse:
    logger.error("Base de données indisponible : %s", exc)
    return JSONResponse(status_code=503, content={"detail": "Base de données indisponible"})


@app.exception_handler(psycopg.errors.UndefinedTable)
async def marts_missing(_: Request, exc: psycopg.errors.UndefinedTable) -> JSONResponse:
    logger.error("Table absente : %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Données non disponibles : lancer le pipeline (dbt build)"},
    )


@app.get("/health", tags=["Technique"], summary="État de l'API et de la base")
def health(repo: Annotated[Repository, Depends(get_repository)]) -> dict[str, str]:
    repo.ping()
    return {"status": "ok", "database": "ok"}
