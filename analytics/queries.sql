-- Requêtes d'analyse ad hoc DuckDB, sur les exports Parquet des marts.
-- Lancer : make analytics   (ou python -m pipeline.export_duckdb --no-export --queries analytics/queries.sql)
-- Elles illustrent ce que DuckDB rend simple : PIVOT, QUALIFY, GROUP BY ALL, fenêtres, Parquet.

-- name: Parts de marché (nombre de systèmes) par édition — top 6 constructeurs
PIVOT (
    SELECT edition, vendor_group, share_systems_pct
    FROM mart_top500_vendor_share
    WHERE vendor_group IN (
        SELECT vendor_group FROM mart_top500_vendor_share
        GROUP BY vendor_group ORDER BY sum(n_systems) DESC LIMIT 6
    )
)
ON edition USING first(share_systems_pct)
ORDER BY vendor_group;

-- name: Les 10 systèmes les plus efficaces énergétiquement (dernière édition)
SELECT rank, system_name, vendor_group, country,
       round(rmax_tflops / 1000, 1)          AS rmax_pflops,
       round(energy_efficiency_gflops_w, 1)  AS gflops_per_watt
FROM top500_systems
WHERE has_power_data
  AND edition = (SELECT max(edition) FROM top500_systems)
ORDER BY energy_efficiency_gflops_w DESC
LIMIT 10;

-- name: Systèmes Bull par pays (dernière édition)
SELECT country, count(*) AS n_systems, round(sum(rmax_tflops) / 1000, 1) AS rmax_pflops,
       min(rank) AS best_rank
FROM top500_systems
WHERE vendor_group = 'Bull'
  AND edition = (SELECT max(edition) FROM top500_systems)
GROUP BY ALL
ORDER BY rmax_pflops DESC;

-- name: Premier mois où le coût cumulé dépasse le budget cumulé (projets en dépassement)
SELECT project_id, cost_month AS first_overrun_month,
       round(cumulative_cost_eur / cumulative_budget_eur * 100 - 100, 1) AS overrun_pct
FROM fct_costs_monthly
WHERE cumulative_cost_eur > cumulative_budget_eur * 1.05
QUALIFY row_number() OVER (PARTITION BY project_id ORDER BY cost_month) = 1
ORDER BY first_overrun_month
LIMIT 10;

-- name: Incidents par segment et par sévérité (délai médian de résolution, heures)
PIVOT (
    SELECT segment, severity, median(resolution_hours) AS median_hours
    FROM fct_incidents
    GROUP BY ALL
)
ON severity IN ('critical', 'high', 'medium', 'low') USING round(first(median_hours), 1)
ORDER BY segment;
