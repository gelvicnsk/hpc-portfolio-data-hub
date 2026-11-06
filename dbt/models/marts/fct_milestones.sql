-- Grain : 1 ligne par jalon. Exposé par GET /projects/{id} (l'API ne lit que le schéma marts).

select
    milestone_id,
    project_id,
    milestone_name,
    planned_date,
    actual_date,
    status,
    actual_date - planned_date      as slip_days

from {{ ref('stg_milestones') }}
