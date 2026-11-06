from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query

from api.db import Settings, get_settings


@dataclass(frozen=True)
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1, description="Numéro de page (à partir de 1)")] = 1,
    page_size: Annotated[int | None, Query(ge=1, description="Éléments par page")] = None,
) -> PageParams:
    size = page_size or settings.api_page_size_default
    if size > settings.api_page_size_max:
        raise HTTPException(
            status_code=422,
            detail=f"page_size maximum : {settings.api_page_size_max}",
        )
    return PageParams(page=page, page_size=size)
