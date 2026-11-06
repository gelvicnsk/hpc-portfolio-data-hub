from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.db import get_repository
from api.pagination import PageParams, page_params
from api.repository import Repository
from api.schemas import ErrorResponse, VendorOrder, VendorShare, VendorSharePage

router = APIRouter(prefix="/top500", tags=["TOP500"])


@router.get(
    "/vendors",
    response_model=VendorSharePage,
    summary="Parts de marché des constructeurs dans le TOP500",
    description=(
        "Part de chaque groupe constructeur en nombre de systèmes et en puissance Rmax, "
        "évolution depuis l'édition précédente et efficacité énergétique. "
        "Sans paramètre `edition`, la dernière édition chargée est utilisée."
    ),
    responses={404: {"model": ErrorResponse, "description": "Édition inconnue"}},
)
def vendor_share(
    repo: Annotated[Repository, Depends(get_repository)],
    paging: Annotated[PageParams, Depends(page_params)],
    edition: Annotated[
        str | None,
        Query(
            pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Édition AAAA-MM", examples=["2026-06"]
        ),
    ] = None,
    order_by: Annotated[VendorOrder, Query(description="Classement")] = VendorOrder.rmax,
) -> VendorSharePage:
    editions = repo.top500_editions()
    if not editions:
        raise HTTPException(status_code=404, detail="Aucune édition TOP500 chargée")
    selected = edition or editions[0]
    if selected not in editions:
        raise HTTPException(
            status_code=404,
            detail=f"Édition {selected} inconnue (disponibles : {', '.join(editions)})",
        )
    rows, total = repo.top500_vendor_share(
        edition=selected, order_by=order_by.value, limit=paging.page_size, offset=paging.offset
    )
    return VendorSharePage(
        edition=selected,
        available_editions=editions,
        items=[VendorShare.model_validate(r) for r in rows],
        total=total,
        page=paging.page,
        page_size=paging.page_size,
        pages=math.ceil(total / paging.page_size) if total else 0,
    )
