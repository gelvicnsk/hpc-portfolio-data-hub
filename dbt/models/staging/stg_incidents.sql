-- Grain : 1 ligne par incident.
-- Aucune ligne n'est écartée ici : clés orphelines, dates inversées et sévérités
-- hors référentiel sont signalées par les tests (warn) puis filtrées dans les marts.

with source as (

    select * from {{ source('raw', 'incidents') }}

)

select
    trim(incident_id)           as incident_id,
    trim(project_id)            as project_id,
    opened_at::timestamp        as opened_at,
    closed_at::timestamp        as closed_at,
    lower(trim(severity))       as severity,
    lower(trim(category))       as category,
    _loaded_at

from source
