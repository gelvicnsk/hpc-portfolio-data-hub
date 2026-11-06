-- Grain : 1 ligne par incident valide.
-- Sert les KPI « incidents ouverts » et « délai moyen de résolution par sévérité »,
-- ainsi que la liste des incidents de GET /projects/{id}.
-- Hypothèse : opened_at / closed_at sont des timestamps dans stg_incidents.

with incidents as (

    select * from {{ ref('int_project_incidents') }}
    where has_known_project      -- écarte les clés orphelines
      and has_consistent_dates   -- écarte closed_at < opened_at
      and has_valid_severity     -- écarte les sévérités hors référentiel

)

select
    incident_id,
    project_id,
    client,
    country,
    segment,
    system_type,
    severity,
    case severity
        when 'critical' then 1
        when 'high'     then 2
        when 'medium'   then 3
        when 'low'      then 4
    end                                                              as severity_rank,
    category,
    opened_at,
    closed_at,
    closed_at is null                                                as is_open,

    case
        when closed_at is not null
            then round((extract(epoch from (closed_at - opened_at)) / 3600.0)::numeric, 2)
    end                                                              as resolution_hours,

    -- âge des incidents encore ouverts (calculé au moment du dbt build)
    case
        when closed_at is null
            then round((extract(epoch from (current_timestamp - opened_at)) / 86400.0)::numeric, 1)
    end                                                              as open_age_days

from incidents
