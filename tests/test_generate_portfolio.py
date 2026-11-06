"""Tests du générateur : reproductibilité, cohérence métier, anomalies en quantité exacte."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from pipeline.generate_portfolio import (
    ANOMALY_COUNTS,
    AS_OF,
    PortfolioData,
    generate,
    main,
    write,
)

EXPECTED_COLUMNS = {
    "projects": [
        "project_id",
        "client",
        "country",
        "segment",
        "system_type",
        "contract_value_eur",
        "start_date",
        "planned_delivery",
        "actual_delivery",
        "status",
    ],
    "milestones": ["milestone_id", "project_id", "name", "planned_date", "actual_date", "status"],
    "incidents": ["incident_id", "project_id", "opened_at", "closed_at", "severity", "category"],
    "costs": ["project_id", "month", "cost_eur", "budget_eur"],
}


@pytest.fixture(scope="module")
def data() -> PortfolioData:
    return generate(seed=42)


# --- reproductibilité -----------------------------------------------------------------


def test_same_seed_same_data(data: PortfolioData) -> None:
    other = generate(seed=42)
    for name, df in data.tables().items():
        pd.testing.assert_frame_equal(df, other.tables()[name])
    assert data.anomalies == other.anomalies


def test_different_seed_different_data(data: PortfolioData) -> None:
    assert not data.projects.equals(generate(seed=7).projects)


# --- structure et volumes -------------------------------------------------------------


def test_columns(data: PortfolioData) -> None:
    for name, df in data.tables().items():
        assert list(df.columns) == EXPECTED_COLUMNS[name]


def test_volumes(data: PortfolioData) -> None:
    assert len(data.projects) == 60 + ANOMALY_COUNTS["duplicate_projects"]
    assert len(data.milestones) == 60 * 7
    assert 150 <= len(data.incidents) <= 500
    assert 600 <= len(data.costs) <= 2500


# --- cohérence métier (hors anomalies) -------------------------------------------------


def test_status_matches_delivery(data: PortfolioData) -> None:
    p = data.projects
    assert set(p["status"]) <= {"livre", "en_cours"}
    assert p.loc[p["status"] == "livre", "actual_delivery"].notna().all()
    assert p.loc[p["status"] == "en_cours", "actual_delivery"].isna().all()


def test_no_actual_date_after_as_of(data: PortfolioData) -> None:
    for col in ("actual_delivery",):
        dates = data.projects[col].dropna().map(date.fromisoformat)
        assert (dates <= AS_OF).all()
    assert (data.milestones["actual_date"].dropna().map(date.fromisoformat) <= AS_OF).all()


def test_milestones_and_costs_have_no_orphans(data: PortfolioData) -> None:
    ids = set(data.projects["project_id"])
    assert set(data.milestones["project_id"]) <= ids
    assert set(data.costs["project_id"]) <= ids


def test_some_projects_late_and_some_over_budget(data: PortfolioData) -> None:
    p = data.projects.drop_duplicates("project_id")
    delivered = p[p["status"] == "livre"]
    late = pd.to_datetime(delivered["actual_delivery"]) > pd.to_datetime(
        delivered["planned_delivery"]
    )
    assert 0.2 < late.mean() < 0.8
    totals = data.costs.groupby("project_id")[["cost_eur", "budget_eur"]].sum()
    assert (totals["cost_eur"] > totals["budget_eur"] * 1.05).any()


def test_open_incidents_only_on_running_projects(data: PortfolioData) -> None:
    inc = data.incidents.merge(
        data.projects.drop_duplicates("project_id")[["project_id", "status"]], on="project_id"
    )
    open_incidents = inc[inc["closed_at"].isna()]
    assert len(open_incidents) >= 10
    assert set(open_incidents["status"]) == {"en_cours"}


# --- anomalies : quantités exactes, retrouvables dans les données ----------------------


def test_anomaly_manifest_counts(data: PortfolioData) -> None:
    assert {k: len(v) for k, v in data.anomalies.items()} == ANOMALY_COUNTS


def test_duplicates_detectable(data: PortfolioData) -> None:
    dups = data.projects[data.projects.duplicated(keep="first")]
    assert sorted(dups["project_id"]) == data.anomalies["duplicate_projects"]


def test_delivery_before_start_detectable(data: PortfolioData) -> None:
    p = data.projects.drop_duplicates()
    bad = p[pd.to_datetime(p["actual_delivery"]) < pd.to_datetime(p["start_date"])]
    assert sorted(bad["project_id"]) == data.anomalies["delivery_before_start"]


def test_negative_costs_detectable(data: PortfolioData) -> None:
    assert (data.costs["cost_eur"] < 0).sum() == ANOMALY_COUNTS["negative_costs"]


def test_incident_anomalies_detectable(data: PortfolioData) -> None:
    inc = data.incidents
    orphans = inc[~inc["project_id"].isin(data.projects["project_id"])]
    assert sorted(orphans["incident_id"]) == data.anomalies["orphan_incidents"]

    inverted = inc[pd.to_datetime(inc["closed_at"]) < pd.to_datetime(inc["opened_at"])]
    assert sorted(inverted["incident_id"]) == data.anomalies["incident_closed_before_opened"]

    invalid = inc[~inc["severity"].isin(["low", "medium", "high", "critical"])]
    assert sorted(invalid["incident_id"]) == data.anomalies["invalid_severity"]


# --- écriture --------------------------------------------------------------------------


def test_write_files_and_manifest(data: PortfolioData, tmp_path: Path) -> None:
    write(data, tmp_path, seed=42)
    for name, columns in EXPECTED_COLUMNS.items():
        df = pd.read_csv(tmp_path / f"{name}.csv")
        assert list(df.columns) == columns
    manifest = json.loads((tmp_path / "anomalies.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 42
    assert manifest["anomalies"]["negative_costs"]["count"] == 4


def test_cli(tmp_path: Path) -> None:
    assert main(["--seed", "1", "--n-projects", "10", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "projects.csv").exists()
