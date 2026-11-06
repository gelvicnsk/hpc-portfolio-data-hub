-- Grain : 1 ligne par projet et par mois (coûts valides uniquement).
-- Cumuls pour suivre la trajectoire budgétaire mois par mois.

with costs as (

    select * from {{ ref('stg_costs') }}
    where cost_eur >= 0          -- anomalie exclue : coûts négatifs (voir assert_costs_positive)

)

select
    cost_id,
    project_id,
    cost_month,
    cost_eur,
    budget_eur,
    cost_eur - budget_eur                                                    as variance_eur,
    sum(cost_eur) over (partition by project_id order by cost_month)        as cumulative_cost_eur,
    sum(budget_eur) over (partition by project_id order by cost_month)      as cumulative_budget_eur

from costs
