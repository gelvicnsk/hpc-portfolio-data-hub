-- Grain : 1 ligne par projet. Coûts cumulés vs budget.
-- Les coûts négatifs (anomalie : avoirs mal saisis) sont exclus du cumul et comptés à part.

with costs as (

    select * from {{ ref('stg_costs') }}

)

select
    project_id,
    count(*)                                                    as n_cost_months,
    count(*) filter (where cost_eur < 0)                        as n_invalid_cost_rows,
    sum(cost_eur) filter (where cost_eur >= 0)                  as total_cost_eur,
    sum(budget_eur)                                             as total_budget_eur,
    sum(cost_eur) filter (where cost_eur >= 0) - sum(budget_eur) as budget_variance_eur,
    round(
        100.0 * (sum(cost_eur) filter (where cost_eur >= 0) - sum(budget_eur))
        / nullif(sum(budget_eur), 0),
        2
    )                                                           as budget_variance_pct

from costs
group by project_id
