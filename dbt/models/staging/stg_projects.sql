-- Grain : 1 ligne par projet.
-- Typage des colonnes texte de raw, renommage, dédoublonnage.
-- Les doublons exacts de l'export sont détectés en amont (test sur la source raw.projects)
-- et éliminés ici ; had_duplicates garde la trace pour l'audit.

with source as (

    select * from {{ source('raw', 'projects') }}

),

deduplicated as (

    select
        *,
        row_number() over (partition by project_id order by _loaded_at desc) as _row_num,
        count(*) over (partition by project_id)                                as _source_rows
    from source

)

select
    trim(project_id)                         as project_id,
    trim(client)                             as client,
    trim(country)                            as country,
    lower(trim(segment))                     as segment,
    trim(system_type)                        as system_type,
    contract_value_eur::numeric(14, 2)       as contract_value_eur,
    start_date::date                         as start_date,
    planned_delivery::date                   as planned_delivery_date,
    actual_delivery::date                    as actual_delivery_date,
    lower(trim(status))                      as status,
    _source_rows > 1                         as had_duplicates,
    _loaded_at

from deduplicated
where _row_num = 1
