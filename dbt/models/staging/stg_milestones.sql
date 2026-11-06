-- Grain : 1 ligne par jalon.

with source as (

    select * from {{ source('raw', 'milestones') }}

)

select
    trim(milestone_id)          as milestone_id,
    trim(project_id)            as project_id,
    trim(name)                  as milestone_name,
    planned_date::date          as planned_date,
    actual_date::date           as actual_date,
    lower(trim(status))         as status,
    _loaded_at

from source
