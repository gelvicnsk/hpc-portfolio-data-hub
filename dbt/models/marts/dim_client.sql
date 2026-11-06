-- Grain : 1 ligne par client.

with projects as (

    select * from {{ ref('stg_projects') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['client']) }}   as client_id,
    client                                               as client_name,
    min(country)                                         as country,
    min(segment)                                         as segment,
    count(*)                                             as n_projects,
    sum(contract_value_eur)                              as total_contract_value_eur,
    min(start_date)                                      as first_project_start

from projects
group by client
