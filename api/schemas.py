"""Modèles Pydantic des réponses : contrat de l'API, documenté automatiquement dans Swagger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):  # noqa: UP046 (pydantic + Python 3.11 compatible)
    items: list[T]
    total: int = Field(description="Nombre total d'éléments, toutes pages confondues")
    page: int
    page_size: int
    pages: int


class ErrorResponse(BaseModel):
    detail: str


# --- KPI ---------------------------------------------------------------------------


class KpiRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope: str
    scope_value: str
    n_projects: int
    n_active_projects: int
    n_delivered_projects: int
    n_overdue_projects: int
    on_time_delivery_pct: Decimal | None = Field(
        description="Part des projets livrés à l'heure (dates cohérentes uniquement)"
    )
    avg_delay_days: Decimal | None = Field(
        description="Retard moyen des projets livrés (une avance compte 0)"
    )
    avg_delay_days_when_late: Decimal | None
    total_budget_eur: Decimal | None
    total_cost_eur: Decimal | None
    budget_variance_eur: Decimal | None
    budget_variance_pct: Decimal | None
    n_projects_over_budget: int
    n_open_incidents: int
    n_critical_incidents: int


class SeverityKpi(BaseModel):
    severity: str
    n_incidents: int
    n_open: int
    avg_resolution_hours: Decimal | None


class PortfolioKpis(BaseModel):
    global_: KpiRow = Field(alias="global", serialization_alias="global")
    by_segment: list[KpiRow]
    by_country: list[KpiRow]
    incidents_by_severity: list[SeverityKpi]

    model_config = ConfigDict(populate_by_name=True)


# --- projets -----------------------------------------------------------------------


class ProjectStatus(StrEnum):
    livre = "livre"
    en_cours = "en_cours"


class ProjectSummary(BaseModel):
    project_id: str
    client_name: str
    country: str
    segment: str
    system_type: str
    status: str
    contract_value_eur: Decimal
    start_date: date
    planned_delivery_date: date
    actual_delivery_date: date | None
    progress_pct: Decimal | None
    delivery_delay_days: int | None
    is_on_time: bool | None
    is_overdue: bool
    budget_variance_pct: Decimal | None
    n_open_incidents: int


class Milestone(BaseModel):
    milestone_id: str
    milestone_name: str
    planned_date: date
    actual_date: date | None
    status: str
    slip_days: int | None


class Incident(BaseModel):
    incident_id: str
    severity: str
    category: str
    opened_at: datetime
    closed_at: datetime | None
    is_open: bool
    resolution_hours: Decimal | None


class ProjectDetail(ProjectSummary):
    client_id: str
    n_milestones: int | None
    n_milestones_done: int | None
    n_milestones_late: int | None
    next_milestone: str | None
    next_milestone_planned_date: date | None
    has_valid_dates: bool
    total_cost_eur: Decimal | None
    total_budget_eur: Decimal | None
    budget_variance_eur: Decimal | None
    is_over_budget: bool
    n_incidents: int
    avg_resolution_hours: Decimal | None
    milestones: list[Milestone]
    incidents: list[Incident]


# --- TOP500 ------------------------------------------------------------------------


class VendorOrder(StrEnum):
    systems = "systems"
    rmax = "rmax"


class VendorShare(BaseModel):
    vendor_group: str
    n_systems: int
    share_systems_pct: Decimal
    rmax_pflops: Decimal
    share_rmax_pct: Decimal
    rank_by_systems: int
    rank_by_rmax: int
    best_system_rank: int | None
    energy_efficiency_gflops_w: Decimal | None = Field(
        description="Rmax / puissance, sur les systèmes qui déclarent leur consommation"
    )
    n_systems_with_power: int
    share_systems_change_pts: Decimal | None = Field(
        description="Évolution de la part (points) depuis l'édition précédente"
    )
    share_rmax_change_pts: Decimal | None


class VendorSharePage(Page[VendorShare]):
    edition: str
    available_editions: list[str]


# --- qualité -----------------------------------------------------------------------


class QualityTest(BaseModel):
    test_name: str
    attached_node: str | None
    column_name: str | None
    severity: str | None
    status: str
    failures: int | None
    message: str | None


class QualityReport(BaseModel):
    invocation_id: str
    generated_at: datetime
    summary: dict[str, int] = Field(description="Nombre de tests par statut")
    tests: list[QualityTest]
