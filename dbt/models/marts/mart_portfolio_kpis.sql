-- KPI de pilotage du portefeuille, à trois niveaux : global, par segment, par pays.
-- Grain : 1 ligne par (scope, scope_value). Lu par GET /kpis/portfolio.

with projects as (

    select * from {{ ref('fct_project_delivery') }}

),

scoped as (

    select 'global' as scope, 'all' as scope_value, * from projects
    union all
    select 'segment', segment, * from projects
    union all
    select 'country', country, * from projects

)

select
    scope,
    scope_value,
    count(*)                                                        as n_projects,
    count(*) filter (where is_active)                               as n_active_projects,
    count(*) filter (where is_delivered)                            as n_delivered_projects,
    count(*) filter (where is_overdue)                              as n_overdue_projects,

    -- livraison à l'heure : projets livrés aux dates cohérentes uniquement
    round(100.0 * avg(case when is_on_time then 1.0 else 0.0 end)
        filter (where is_on_time is not null), 1)                   as on_time_delivery_pct,
    -- retard moyen des projets livrés : une livraison en avance compte 0 jour de retard.
    -- Attention : greatest(NULL, 0) vaut 0 en PostgreSQL, d'où le filtre explicite.
    round(avg(greatest(delivery_delay_days, 0))
        filter (where delivery_delay_days is not null), 1)          as avg_delay_days,
    round(avg(delivery_delay_days) filter (where delivery_delay_days > 0), 1)
                                                                    as avg_delay_days_when_late,

    sum(total_budget_eur)                                           as total_budget_eur,
    sum(total_cost_eur)                                             as total_cost_eur,
    sum(total_cost_eur) - sum(total_budget_eur)                     as budget_variance_eur,
    round(100.0 * (sum(total_cost_eur) - sum(total_budget_eur))
        / nullif(sum(total_budget_eur), 0), 2)                      as budget_variance_pct,
    count(*) filter (where is_over_budget)                          as n_projects_over_budget,

    sum(n_open_incidents)                                           as n_open_incidents,
    sum(n_critical_incidents)                                       as n_critical_incidents

from scoped
group by scope, scope_value
