-- Grain : 1 ligne par projet. Avancement et glissement des jalons.

with milestones as (

    select * from {{ ref('stg_milestones') }}

)

select
    project_id,
    count(*)                                                        as n_milestones,
    count(*) filter (where status = 'termine')                      as n_milestones_done,
    count(*) filter (where status = 'en_retard')                    as n_milestones_late,
    round(100.0 * count(*) filter (where status = 'termine') / count(*), 1)
                                                                    as progress_pct,
    -- glissement maximal constaté sur un jalon terminé (jours, négatif = en avance)
    max(actual_date - planned_date) filter (where actual_date is not null)
                                                                    as max_milestone_slip_days,
    (array_agg(milestone_name order by planned_date)
        filter (where status <> 'termine'))[1]                      as next_milestone,
    min(planned_date) filter (where status <> 'termine')            as next_milestone_planned_date

from milestones
group by project_id
