-- Grain : 1 ligne par projet. Attributs descriptifs + avancement des jalons.

with projects as (

    select * from {{ ref('stg_projects') }}

),

milestones as (

    select * from {{ ref('int_project_milestones') }}

)

select
    projects.project_id,
    {{ dbt_utils.generate_surrogate_key(['projects.client']) }}   as client_id,
    projects.client                                              as client_name,
    projects.country,
    projects.segment,
    projects.system_type,
    projects.contract_value_eur,
    projects.status,
    projects.start_date,
    projects.planned_delivery_date,
    projects.actual_delivery_date,
    milestones.n_milestones,
    milestones.n_milestones_done,
    milestones.n_milestones_late,
    milestones.progress_pct,
    milestones.next_milestone,
    milestones.next_milestone_planned_date,
    projects.had_duplicates

from projects
left join milestones
    on projects.project_id = milestones.project_id
