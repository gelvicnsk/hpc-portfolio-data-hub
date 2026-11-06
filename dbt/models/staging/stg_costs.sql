-- Grain : 1 ligne par projet et par mois.

with source as (

    select * from {{ source('raw', 'costs') }}

)

select
    trim(project_id) || '-' || to_char(month::date, 'YYYY-MM')   as cost_id,
    trim(project_id)                                              as project_id,
    month::date                                                   as cost_month,
    cost_eur::numeric(14, 2)                                      as cost_eur,
    budget_eur::numeric(14, 2)                                    as budget_eur,
    _loaded_at

from source
