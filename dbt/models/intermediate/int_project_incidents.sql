-- Grain : 1 ligne par incident, enrichie du contexte projet.
-- On garde TOUS les incidents (left join) et on marque les anomalies
-- au lieu de les supprimer : le filtrage se fait dans fct_incidents,
-- et les lignes écartées restent auditables ici.

with incidents as (

    select * from {{ ref('stg_incidents') }}

),

projects as (

    select
        project_id,
        client,
        country,
        segment,
        system_type
    from {{ ref('stg_projects') }}

)

select
    incidents.incident_id,
    incidents.project_id,
    projects.client,
    projects.country,
    projects.segment,
    projects.system_type,
    incidents.severity,
    incidents.category,
    incidents.opened_at,
    incidents.closed_at,

    -- contrôles qualité
    projects.project_id is not null                                as has_known_project,
    (incidents.closed_at is null
        or incidents.closed_at >= incidents.opened_at)              as has_consistent_dates,
    incidents.severity in ('low', 'medium', 'high', 'critical')     as has_valid_severity

from incidents
left join projects
    on incidents.project_id = projects.project_id
