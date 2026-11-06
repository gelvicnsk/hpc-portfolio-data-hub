-- Grain : 1 ligne par projet. Mesures de délai, de budget et d'incidents.
-- Date de référence : var('as_of_date') (données synthétiques figées au 31/10/2026).

{% set as_of = "'" ~ var('as_of_date') ~ "'::date" %}

with projects as (

    select * from {{ ref('stg_projects') }}

),

costs as (

    select * from {{ ref('int_project_costs') }}

),

incidents as (

    select
        project_id,
        count(*)                                        as n_incidents,
        count(*) filter (where is_open)                 as n_open_incidents,
        count(*) filter (where severity = 'critical')   as n_critical_incidents,
        avg(resolution_hours)                           as avg_resolution_hours
    from {{ ref('fct_incidents') }}
    group by project_id

),

delivery as (

    select
        *,
        actual_delivery_date is null or actual_delivery_date >= start_date   as has_valid_dates
    from projects

)

select
    delivery.project_id,
    {{ dbt_utils.generate_surrogate_key(['delivery.client']) }}   as client_id,
    delivery.segment,
    delivery.country,
    delivery.status,
    delivery.contract_value_eur,
    delivery.start_date,
    delivery.planned_delivery_date,
    delivery.actual_delivery_date,
    delivery.has_valid_dates,

    delivery.status = 'livre'                                     as is_delivered,
    delivery.status = 'en_cours'                                  as is_active,

    -- délai : seulement pour les projets livrés aux dates cohérentes
    case when delivery.status = 'livre' and delivery.has_valid_dates
        then delivery.actual_delivery_date - delivery.planned_delivery_date
    end                                                           as delivery_delay_days,
    case when delivery.status = 'livre' and delivery.has_valid_dates
        then delivery.actual_delivery_date <= delivery.planned_delivery_date
    end                                                           as is_on_time,
    -- projet en cours dont la date de livraison prévue est déjà dépassée
    delivery.status = 'en_cours'
        and delivery.planned_delivery_date < {{ as_of }}          as is_overdue,

    costs.total_cost_eur,
    costs.total_budget_eur,
    costs.budget_variance_eur,
    costs.budget_variance_pct,
    coalesce(costs.budget_variance_pct > 5, false)                as is_over_budget,
    coalesce(costs.n_invalid_cost_rows, 0)                        as n_invalid_cost_rows,

    coalesce(incidents.n_incidents, 0)                            as n_incidents,
    coalesce(incidents.n_open_incidents, 0)                       as n_open_incidents,
    coalesce(incidents.n_critical_incidents, 0)                   as n_critical_incidents,
    round(incidents.avg_resolution_hours::numeric, 1)             as avg_resolution_hours

from delivery
left join costs
    on delivery.project_id = costs.project_id
left join incidents
    on delivery.project_id = incidents.project_id
