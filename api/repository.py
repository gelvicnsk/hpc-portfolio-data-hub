"""Requêtes SQL de l'API, toutes en lecture sur les schémas marts et meta.

Isolées ici pour que les routeurs restent sans SQL et que les tests puissent remplacer
le Repository par une implémentation en mémoire.
"""

from __future__ import annotations

from typing import Any

import psycopg

Row = dict[str, Any]


class Repository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def _all(self, query: str, params: tuple | dict = ()) -> list[Row]:
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            return list(cur.fetchall())

    def _one(self, query: str, params: tuple | dict = ()) -> Row | None:
        rows = self._all(query, params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        return self._one("SELECT 1 AS ok") is not None

    # --- KPI ---------------------------------------------------------------------

    def portfolio_kpis(self) -> list[Row]:
        return self._all("SELECT * FROM marts.mart_portfolio_kpis ORDER BY scope, scope_value")

    def incidents_by_severity(self) -> list[Row]:
        return self._all(
            """
            SELECT severity,
                   count(*)                                   AS n_incidents,
                   count(*) FILTER (WHERE is_open)            AS n_open,
                   round(avg(resolution_hours)::numeric, 1)   AS avg_resolution_hours
            FROM marts.fct_incidents
            GROUP BY severity, severity_rank
            ORDER BY severity_rank
            """
        )

    # --- projets -----------------------------------------------------------------

    def list_projects(
        self, *, status: str | None, segment: str | None, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        filters = {"status": status, "segment": segment}
        where = " AND ".join(f"p.{col} = %({col})s" for col, v in filters.items() if v)
        where_sql = f"WHERE {where}" if where else ""
        params: dict[str, Any] = {**filters, "limit": limit, "offset": offset}
        total = self._one(f"SELECT count(*) AS n FROM marts.dim_project p {where_sql}", params)
        rows = self._all(
            f"""
            SELECT p.project_id, p.client_name, p.country, p.segment, p.system_type,
                   p.status, p.contract_value_eur, p.start_date, p.planned_delivery_date,
                   p.actual_delivery_date, p.progress_pct, d.delivery_delay_days,
                   d.is_on_time, d.is_overdue, d.budget_variance_pct, d.n_open_incidents
            FROM marts.dim_project p
            JOIN marts.fct_project_delivery d USING (project_id)
            {where_sql}
            ORDER BY p.project_id
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            params,
        )
        return rows, int(total["n"]) if total else 0

    def get_project(self, project_id: str) -> Row | None:
        return self._one(
            """
            SELECT p.*, d.delivery_delay_days, d.is_on_time, d.is_overdue, d.has_valid_dates,
                   d.total_cost_eur, d.total_budget_eur, d.budget_variance_eur,
                   d.budget_variance_pct, d.is_over_budget, d.n_incidents,
                   d.n_open_incidents, d.avg_resolution_hours
            FROM marts.dim_project p
            JOIN marts.fct_project_delivery d USING (project_id)
            WHERE p.project_id = %s
            """,
            (project_id,),
        )

    def project_milestones(self, project_id: str) -> list[Row]:
        return self._all(
            """
            SELECT milestone_id, milestone_name, planned_date, actual_date, status, slip_days
            FROM marts.fct_milestones WHERE project_id = %s ORDER BY planned_date
            """,
            (project_id,),
        )

    def project_incidents(self, project_id: str) -> list[Row]:
        return self._all(
            """
            SELECT incident_id, severity, category, opened_at, closed_at, is_open,
                   resolution_hours
            FROM marts.fct_incidents WHERE project_id = %s
            ORDER BY opened_at DESC
            """,
            (project_id,),
        )

    # --- TOP500 ------------------------------------------------------------------

    def top500_editions(self) -> list[str]:
        rows = self._all(
            "SELECT DISTINCT edition FROM marts.mart_top500_vendor_share ORDER BY edition DESC"
        )
        return [r["edition"] for r in rows]

    def top500_vendor_share(
        self, *, edition: str, order_by: str, limit: int, offset: int
    ) -> tuple[list[Row], int]:
        # order_by est validé par l'API (Enum) : jamais de valeur libre dans le SQL
        order_column = {"systems": "rank_by_systems", "rmax": "rank_by_rmax"}[order_by]
        total = self._one(
            "SELECT count(*) AS n FROM marts.mart_top500_vendor_share WHERE edition = %s",
            (edition,),
        )
        rows = self._all(
            f"""
            SELECT vendor_group, n_systems, share_systems_pct, rmax_pflops, share_rmax_pct,
                   rank_by_systems, rank_by_rmax, best_system_rank,
                   energy_efficiency_gflops_w, n_systems_with_power,
                   share_systems_change_pts, share_rmax_change_pts
            FROM marts.mart_top500_vendor_share
            WHERE edition = %s
            ORDER BY {order_column}, vendor_group
            LIMIT %s OFFSET %s
            """,
            (edition, limit, offset),
        )
        return rows, int(total["n"]) if total else 0

    # --- qualité -----------------------------------------------------------------

    def latest_quality_results(self) -> list[Row]:
        return self._all(
            """
            SELECT invocation_id, generated_at, test_name, attached_node, column_name,
                   severity, status, failures, message
            FROM meta.v_latest_test_results
            ORDER BY CASE status WHEN 'error' THEN 0 WHEN 'fail' THEN 1
                                 WHEN 'warn' THEN 2 ELSE 3 END, test_name
            """
        )
