"""Charge les résultats des tests dbt dans meta.dbt_test_results.

Après `dbt build`, dbt écrit `target/run_results.json` (statut de chaque nœud)
et `target/manifest.json` (métadonnées : modèle testé, colonne, sévérité).
Ce module ne garde que les tests, les enrichit avec le manifest et les insère
dans PostgreSQL. L'API les expose ensuite via GET /quality/report.

Usage :
    python -m pipeline.quality --target-dir dbt/target
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from pipeline.db import connect

logger = logging.getLogger(__name__)

DEFAULT_TARGET_DIR = Path(os.getenv("DBT_TARGET_PATH", "dbt/target"))

INSERT_SQL = """
    INSERT INTO meta.dbt_test_results (
        invocation_id, generated_at, unique_id, test_name, attached_node,
        column_name, severity, status, failures, message, execution_time_s
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class DbtTestResult:
    """Un test dbt exécuté. L'ordre des champs suit INSERT_SQL."""

    invocation_id: str
    generated_at: datetime
    unique_id: str
    test_name: str
    attached_node: str | None
    column_name: str | None
    severity: str | None
    status: str
    failures: int | None
    message: str | None
    execution_time_s: float


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _test_name_from_unique_id(unique_id: str) -> str:
    # test.<projet>.<nom_du_test>.<hash>
    parts = unique_id.split(".")
    return parts[2] if len(parts) > 2 else unique_id


def parse_run_results(
    run_results_path: Path, manifest_path: Path | None = None
) -> list[DbtTestResult]:
    """Lit run_results.json (+ manifest.json s'il existe) et renvoie les tests."""
    run_results = _read_json(run_results_path)
    nodes: dict[str, Any] = {}
    if manifest_path is not None and manifest_path.exists():
        nodes = _read_json(manifest_path).get("nodes", {})

    metadata = run_results.get("metadata", {})
    invocation_id = str(metadata.get("invocation_id") or "unknown")
    generated_at = _parse_timestamp(metadata.get("generated_at"))

    results: list[DbtTestResult] = []
    for item in run_results.get("results", []):
        unique_id = str(item.get("unique_id", ""))
        if not unique_id.startswith("test."):
            continue  # modèles, seeds, snapshots : hors périmètre qualité
        node = nodes.get(unique_id, {})
        config = node.get("config", {})
        failures = item.get("failures")
        results.append(
            DbtTestResult(
                invocation_id=invocation_id,
                generated_at=generated_at,
                unique_id=unique_id,
                test_name=node.get("name") or _test_name_from_unique_id(unique_id),
                attached_node=node.get("attached_node"),
                column_name=node.get("column_name"),
                severity=config.get("severity"),
                status=str(item.get("status", "unknown")),
                failures=int(failures) if failures is not None else None,
                message=item.get("message"),
                execution_time_s=float(item.get("execution_time") or 0.0),
            )
        )
    return results


def load_test_results(conn: psycopg.Connection, results: list[DbtTestResult]) -> int:
    """Insère les résultats d'un run. Idempotent : un même run rechargé remplace l'ancien."""
    if not results:
        return 0
    invocation_ids = {r.invocation_id for r in results}
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "DELETE FROM meta.dbt_test_results WHERE invocation_id = ANY(%s)",
            (list(invocation_ids),),
        )
        cur.executemany(INSERT_SQL, [astuple(r) for r in results])
    return len(results)


def summarize(results: list[DbtTestResult]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for r in results:
        summary[r.status] = summary.get(r.status, 0) + 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    args = parser.parse_args(argv)

    run_results_path = args.target_dir / "run_results.json"
    if not run_results_path.exists():
        logger.error("Fichier introuvable : %s (lancer `dbt build` avant)", run_results_path)
        return 1

    results = parse_run_results(run_results_path, args.target_dir / "manifest.json")
    with connect(autocommit=False) as conn:
        loaded = load_test_results(conn, results)

    logger.info("%d résultats de tests chargés — %s", loaded, summarize(results))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
