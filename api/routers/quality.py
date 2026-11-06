from __future__ import annotations

from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.db import get_repository
from api.repository import Repository
from api.schemas import ErrorResponse, QualityReport, QualityTest

router = APIRouter(prefix="/quality", tags=["Qualité"])


@router.get(
    "/report",
    response_model=QualityReport,
    summary="Résultat des derniers tests qualité dbt",
    description=(
        "Tests du dernier `dbt build` (chargés par pipeline/quality.py). Les tests en `warn` "
        "correspondent aux anomalies connues des données sources."
    ),
    responses={404: {"model": ErrorResponse, "description": "Aucun run dbt chargé"}},
)
def quality_report(repo: Annotated[Repository, Depends(get_repository)]) -> QualityReport:
    rows = repo.latest_quality_results()
    if not rows:
        raise HTTPException(status_code=404, detail="Aucun résultat qualité : lancer le pipeline")
    return QualityReport(
        invocation_id=rows[0]["invocation_id"],
        generated_at=rows[0]["generated_at"],
        summary=dict(Counter(r["status"] for r in rows)),
        tests=[QualityTest.model_validate(r) for r in rows],
    )
