"""Tests de l'API avec un Repository en mémoire (aucune base nécessaire).

Ils vérifient le contrat HTTP : codes de retour, validation, pagination, format des
réponses. Les requêtes SQL elles-mêmes sont couvertes par le dbt build en CI.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.db import Settings, get_repository, get_settings
from api.main import app


def kpi(scope: str, value: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "scope": scope,
        "scope_value": value,
        "n_projects": 60,
        "n_active_projects": 16,
        "n_delivered_projects": 44,
        "n_overdue_projects": 3,
        "on_time_delivery_pct": Decimal("54.8"),
        "avg_delay_days": Decimal("18.6"),
        "avg_delay_days_when_late": Decimal("41.1"),
        "total_budget_eur": Decimal("1231437970.01"),
        "total_cost_eur": Decimal("1217515626.10"),
        "budget_variance_eur": Decimal("-13922343.91"),
        "budget_variance_pct": Decimal("-1.13"),
        "n_projects_over_budget": 13,
        "n_open_incidents": 13,
        "n_critical_incidents": 17,
    }
    return {**row, **overrides}


PROJECT = {
    "project_id": "P0001",
    "client_id": "abc",
    "client_name": "Centre de calcul Helios",
    "country": "Germany",
    "segment": "recherche",
    "system_type": "BullSequana XH3000",
    "status": "en_cours",
    "contract_value_eur": Decimal("41967000"),
    "start_date": date(2025, 6, 24),
    "planned_delivery_date": date(2027, 5, 24),
    "actual_delivery_date": None,
    "progress_pct": Decimal("42.9"),
    "delivery_delay_days": None,
    "is_on_time": None,
    "is_overdue": False,
    "budget_variance_pct": Decimal("-3.2"),
    "n_open_incidents": 1,
    "n_milestones": 7,
    "n_milestones_done": 3,
    "n_milestones_late": 0,
    "next_milestone": "Livraison sur site",
    "next_milestone_planned_date": date(2026, 12, 1),
    "has_valid_dates": True,
    "total_cost_eur": Decimal("1000"),
    "total_budget_eur": Decimal("1033"),
    "budget_variance_eur": Decimal("-33"),
    "is_over_budget": False,
    "n_incidents": 2,
    "avg_resolution_hours": Decimal("12.5"),
    "had_duplicates": False,
}

VENDOR = {
    "vendor_group": "Bull",
    "n_systems": 58,
    "share_systems_pct": Decimal("11.60"),
    "rmax_pflops": Decimal("1997.7"),
    "share_rmax_pct": Decimal("10.66"),
    "rank_by_systems": 3,
    "rank_by_rmax": 3,
    "best_system_rank": 5,
    "energy_efficiency_gflops_w": Decimal("27.38"),
    "n_systems_with_power": 30,
    "share_systems_change_pts": None,
    "share_rmax_change_pts": None,
}


class FakeRepository:
    def __init__(self, projects: int = 45) -> None:
        self.projects = [{**PROJECT, "project_id": f"P{i:04d}"} for i in range(1, projects + 1)]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ping(self) -> bool:
        return True

    def portfolio_kpis(self) -> list[dict[str, Any]]:
        return [
            kpi("country", "France", n_projects=20),
            kpi("global", "all"),
            kpi("segment", "meteo", n_projects=10, budget_variance_pct=Decimal("11.81")),
        ]

    def incidents_by_severity(self) -> list[dict[str, Any]]:
        return [
            {"severity": "critical", "n_incidents": 26, "n_open": 2, "avg_resolution_hours": 9.8}
        ]

    def list_projects(self, *, status, segment, limit, offset):
        self.calls.append(("list_projects", {"status": status, "segment": segment}))
        rows = self.projects
        return rows[offset : offset + limit], len(rows)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return next((p for p in self.projects if p["project_id"] == project_id), None)

    def project_milestones(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "milestone_id": "M00001",
                "milestone_name": "Signature du contrat",
                "planned_date": date(2025, 6, 24),
                "actual_date": date(2025, 6, 24),
                "status": "termine",
                "slip_days": 0,
            }
        ]

    def project_incidents(self, project_id: str) -> list[dict[str, Any]]:
        return [
            {
                "incident_id": "I00001",
                "severity": "medium",
                "category": "materiel",
                "opened_at": datetime(2025, 11, 29, 3, 23),
                "closed_at": None,
                "is_open": True,
                "resolution_hours": None,
            }
        ]

    def top500_editions(self) -> list[str]:
        return ["2026-06", "2025-11"]

    def top500_vendor_share(self, *, edition, order_by, limit, offset):
        self.calls.append(("top500", {"edition": edition, "order_by": order_by}))
        return [VENDOR], 1

    def latest_quality_results(self) -> list[dict[str, Any]]:
        base = {
            "invocation_id": "run-1",
            "generated_at": datetime(2026, 11, 6, 11, 0),
            "attached_node": None,
            "column_name": None,
            "severity": "warn",
            "message": None,
        }
        return [
            {**base, "test_name": "assert_costs_positive", "status": "warn", "failures": 4},
            {
                **base,
                "test_name": "unique_stg_projects_project_id",
                "status": "pass",
                "failures": 0,
            },
        ]


class BrokenRepository(FakeRepository):
    def portfolio_kpis(self):
        raise psycopg.OperationalError("connection refused")


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(repo: FakeRepository) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_settings] = lambda: Settings(api_db_password="test")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- technique ---------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


def test_openapi_documents_all_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {
        "/kpis/portfolio",
        "/projects/{project_id}",
        "/top500/vendors",
        "/quality/report",
    } <= set(paths)


def test_database_down_returns_503(client: TestClient) -> None:
    app.dependency_overrides[get_repository] = lambda: BrokenRepository()
    response = client.get("/kpis/portfolio")
    assert response.status_code == 503
    assert response.json()["detail"] == "Base de données indisponible"


# --- KPI ---------------------------------------------------------------------------


def test_portfolio_kpis(client: TestClient) -> None:
    body = client.get("/kpis/portfolio").json()
    assert body["global"]["on_time_delivery_pct"] == "54.8"
    assert body["global"]["n_active_projects"] == 16
    assert [r["scope_value"] for r in body["by_segment"]] == ["meteo"]
    assert [r["scope_value"] for r in body["by_country"]] == ["France"]
    assert body["incidents_by_severity"][0]["severity"] == "critical"


# --- projets -----------------------------------------------------------------------


def test_projects_pagination(client: TestClient) -> None:
    body = client.get("/projects", params={"page": 3, "page_size": 20}).json()
    assert body["total"] == 45
    assert body["pages"] == 3
    assert [p["project_id"] for p in body["items"]] == [f"P{i:04d}" for i in range(41, 46)]


def test_projects_page_size_limit(client: TestClient) -> None:
    assert client.get("/projects", params={"page_size": 500}).status_code == 422
    assert client.get("/projects", params={"page": 0}).status_code == 422


def test_projects_filters_are_validated_and_forwarded(
    client: TestClient, repo: FakeRepository
) -> None:
    assert client.get("/projects", params={"status": "inconnu"}).status_code == 422
    client.get("/projects", params={"status": "livre", "segment": "meteo"})
    assert repo.calls[-1] == ("list_projects", {"status": "livre", "segment": "meteo"})


def test_project_detail(client: TestClient) -> None:
    body = client.get("/projects/P0001").json()
    assert body["project_id"] == "P0001"
    assert body["next_milestone"] == "Livraison sur site"
    assert body["milestones"][0]["status"] == "termine"
    assert body["incidents"][0]["is_open"] is True


def test_project_not_found(client: TestClient) -> None:
    response = client.get("/projects/P9999")
    assert response.status_code == 404
    assert "P9999" in response.json()["detail"]


def test_project_id_format_is_validated(client: TestClient) -> None:
    assert client.get("/projects/1;DROP TABLE").status_code == 422


# --- TOP500 ------------------------------------------------------------------------


def test_top500_defaults_to_latest_edition(client: TestClient, repo: FakeRepository) -> None:
    body = client.get("/top500/vendors").json()
    assert body["edition"] == "2026-06"
    assert body["available_editions"] == ["2026-06", "2025-11"]
    assert body["items"][0]["vendor_group"] == "Bull"
    assert repo.calls[-1] == ("top500", {"edition": "2026-06", "order_by": "rmax"})


def test_top500_explicit_edition_and_order(client: TestClient, repo: FakeRepository) -> None:
    client.get("/top500/vendors", params={"edition": "2025-11", "order_by": "systems"})
    assert repo.calls[-1] == ("top500", {"edition": "2025-11", "order_by": "systems"})


def test_top500_unknown_edition(client: TestClient) -> None:
    response = client.get("/top500/vendors", params={"edition": "1999-06"})
    assert response.status_code == 404
    assert "2026-06" in response.json()["detail"]


def test_top500_invalid_edition_format(client: TestClient) -> None:
    assert client.get("/top500/vendors", params={"edition": "juin"}).status_code == 422
    assert client.get("/top500/vendors", params={"order_by": "prix"}).status_code == 422


# --- qualité -----------------------------------------------------------------------


def test_quality_report(client: TestClient) -> None:
    body = client.get("/quality/report").json()
    assert body["summary"] == {"warn": 1, "pass": 1}
    assert body["tests"][0]["test_name"] == "assert_costs_positive"
    assert body["tests"][0]["failures"] == 4
