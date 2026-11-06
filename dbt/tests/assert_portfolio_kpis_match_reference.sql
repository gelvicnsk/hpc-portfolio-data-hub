-- Test de non-régression des KPI globaux sur les données synthétiques de référence (seed 42).
-- Valeurs recalculées indépendamment en pandas depuis les CSV.
-- Si les données sont régénérées avec un autre seed, ce test est sans objet : il ne
-- s'exécute que lorsque le portefeuille de référence (60 projets) est chargé.
{{ config(severity='warn') }}

with kpis as (

    select * from {{ ref('mart_portfolio_kpis') }}
    where scope = 'global'

),

expected as (

    select
        60     as n_projects,
        16     as n_active_projects,
        44     as n_delivered_projects,
        54.8   as on_time_delivery_pct,
        18.6   as avg_delay_days,
        -1.13  as budget_variance_pct,
        13     as n_projects_over_budget,
        13     as n_open_incidents

)

select kpis.*
from kpis
cross join expected
where kpis.n_projects = expected.n_projects
  and (
       kpis.n_active_projects      <> expected.n_active_projects
    or kpis.n_delivered_projects   <> expected.n_delivered_projects
    or kpis.on_time_delivery_pct   <> expected.on_time_delivery_pct
    or kpis.avg_delay_days         <> expected.avg_delay_days
    or kpis.budget_variance_pct    <> expected.budget_variance_pct
    or kpis.n_projects_over_budget <> expected.n_projects_over_budget
    or kpis.n_open_incidents       <> expected.n_open_incidents
  )
