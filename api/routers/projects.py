from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from api.db import get_repository
from api.pagination import PageParams, page_params
from api.repository import Repository
from api.schemas import (
    ErrorResponse,
    Incident,
    Milestone,
    Page,
    ProjectDetail,
    ProjectStatus,
    ProjectSummary,
)

router = APIRouter(prefix="/projects", tags=["Projets"])

ProjectId = Annotated[
    str,
    Path(pattern=r"^P\d{4}$", description="Identifiant projet, ex. P0001", examples=["P0001"]),
]


@router.get("", response_model=Page[ProjectSummary], summary="Liste paginée des projets")
def list_projects(
    repo: Annotated[Repository, Depends(get_repository)],
    paging: Annotated[PageParams, Depends(page_params)],
    status: Annotated[ProjectStatus | None, Query(description="Filtrer par statut")] = None,
    segment: Annotated[str | None, Query(description="Filtrer par segment")] = None,
) -> Page[ProjectSummary]:
    rows, total = repo.list_projects(
        status=status.value if status else None,
        segment=segment,
        limit=paging.page_size,
        offset=paging.offset,
    )
    return Page[ProjectSummary](
        items=[ProjectSummary.model_validate(r) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
        pages=math.ceil(total / paging.page_size) if total else 0,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetail,
    summary="Détail d'un projet, avec ses jalons et ses incidents",
    responses={404: {"model": ErrorResponse, "description": "Projet inconnu"}},
)
def get_project(
    project_id: ProjectId, repo: Annotated[Repository, Depends(get_repository)]
) -> ProjectDetail:
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Projet {project_id} introuvable")
    return ProjectDetail.model_validate(
        {
            **project,
            "milestones": [
                Milestone.model_validate(m) for m in repo.project_milestones(project_id)
            ],
            "incidents": [Incident.model_validate(i) for i in repo.project_incidents(project_id)],
        }
    )
