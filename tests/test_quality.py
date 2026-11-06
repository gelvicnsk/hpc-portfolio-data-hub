"""Tests du parsing des artefacts dbt (sans base de données)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.quality import parse_run_results, summarize


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    run_results = _write_json(
        tmp_path / "run_results.json",
        {
            "metadata": {"invocation_id": "run-1", "generated_at": "2026-11-06T09:00:00.000000Z"},
            "results": [
                {"unique_id": "model.hpc_hub.stg_projects", "status": "success"},
                {
                    "unique_id": "test.hpc_hub.unique_stg_projects_project_id.abc123",
                    "status": "pass",
                    "failures": 0,
                    "execution_time": 0.12,
                },
                {
                    "unique_id": "test.hpc_hub.assert_costs_positive",
                    "status": "warn",
                    "failures": 3,
                    "message": "Got 3 results, configured to warn if != 0",
                    "execution_time": 0.05,
                },
            ],
        },
    )
    manifest = _write_json(
        tmp_path / "manifest.json",
        {
            "nodes": {
                "test.hpc_hub.unique_stg_projects_project_id.abc123": {
                    "name": "unique_stg_projects_project_id",
                    "attached_node": "model.hpc_hub.stg_projects",
                    "column_name": "project_id",
                    "config": {"severity": "ERROR"},
                }
            }
        },
    )
    return run_results, manifest


def test_only_tests_are_kept(tmp_path: Path) -> None:
    run_results, manifest = _artifacts(tmp_path)
    results = parse_run_results(run_results, manifest)
    assert [r.unique_id.split(".")[0] for r in results] == ["test", "test"]


def test_manifest_enrichment(tmp_path: Path) -> None:
    run_results, manifest = _artifacts(tmp_path)
    unique_test = parse_run_results(run_results, manifest)[0]
    assert unique_test.test_name == "unique_stg_projects_project_id"
    assert unique_test.column_name == "project_id"
    assert unique_test.severity == "ERROR"
    assert unique_test.generated_at.tzinfo is not None


def test_works_without_manifest(tmp_path: Path) -> None:
    run_results, _ = _artifacts(tmp_path)
    results = parse_run_results(run_results, tmp_path / "absent.json")
    assert results[1].test_name == "assert_costs_positive"
    assert results[1].failures == 3


def test_summarize(tmp_path: Path) -> None:
    run_results, manifest = _artifacts(tmp_path)
    assert summarize(parse_run_results(run_results, manifest)) == {"pass": 1, "warn": 1}
