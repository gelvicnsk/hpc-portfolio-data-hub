from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.db import get_repository
from api.repository import Repository
from api.schemas import KpiRow, PortfolioKpis, SeverityKpi

router = APIRouter(prefix="/kpis", tags=["KPI"])


@router.get(
    "/portfolio",
    response_model=PortfolioKpis,
    response_model_by_alias=True,
    summary="KPI du portefeuille HPC",
    description=(
        "Projets actifs, taux de livraison à l'heure, retard moyen, dépassement budgétaire "
        "et incidents — en global, par segment et par pays."
    ),
)
def portfolio_kpis(repo: Annotated[Repository, Depends(get_repository)]) -> PortfolioKpis:
    rows = [KpiRow.model_validate(r) for r in repo.portfolio_kpis()]
    global_rows = [r for r in rows if r.scope == "global"]
    if not global_rows:
        raise HTTPException(status_code=404, detail="KPI indisponibles : lancer le pipeline")
    return PortfolioKpis(
        global_=global_rows[0],
        by_segment=[r for r in rows if r.scope == "segment"],
        by_country=[r for r in rows if r.scope == "country"],
        incidents_by_severity=[SeverityKpi.model_validate(r) for r in repo.incidents_by_severity()],
    )
