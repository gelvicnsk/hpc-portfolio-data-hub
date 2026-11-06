-- Grain : 1 ligne par (édition, rang).
-- Typage, dédoublonnage (rechargements), nom de système par défaut,
-- regroupement des constructeurs via le seed vendor_mapping.

with source as (

    select * from {{ source('raw', 'top500') }}

),

deduplicated as (

    -- un fichier rechargé deux fois ne doit pas doubler l'édition : on garde le dernier chargement
    select
        *,
        row_number() over (
            partition by edition, rank
            order by _loaded_at desc
        ) as _row_num
    from source

),

typed as (

    select
        edition || '-' || lpad(rank::integer::text, 3, '0')               as top500_entry_id,
        edition,
        to_date(edition || '-01', 'YYYY-MM-DD')                          as edition_date,
        rank::integer                                                    as rank,
        previous_rank::integer                                           as previous_rank,
        previous_rank is null                                            as is_new_entry,

        coalesce(nullif(trim(system_name), ''), trim(computer))          as system_name,
        trim(computer)                                                   as computer,
        trim(site)                                                       as site,
        trim(country)                                                    as country,
        trim(continent)                                                  as continent,
        year::integer                                                    as installation_year,
        trim(segment)                                                    as segment,

        trim(manufacturer)                                               as manufacturer_raw,
        {{ normalize_vendor('manufacturer') }}                           as manufacturer_key,
        {{ normalize_vendor(primary_vendor('manufacturer')) }}           as manufacturer_primary_key,
        {{ primary_vendor('manufacturer') }}                             as manufacturer_primary,
        manufacturer ~ '[/,]'                                            as is_multi_vendor,

        cores::bigint                                                    as cores,
        rmax_tflops::numeric                                             as rmax_tflops,
        rpeak_tflops::numeric                                            as rpeak_tflops,
        power_kw::numeric                                                as power_kw,
        power_kw is not null and power_kw::numeric > 0                   as has_power_data,

        -- valeur officielle si présente, sinon Rmax (TFlop/s) / Power (kW) = GFlops/W
        coalesce(
            energy_efficiency_gflops_w::numeric,
            rmax_tflops::numeric / nullif(power_kw::numeric, 0)
        )                                                                as energy_efficiency_gflops_w,

        trim(processor)                                                  as processor,
        nullif(trim(accelerator), '')                                    as accelerator,
        nullif(trim(accelerator), '') is not null                        as has_accelerator,
        trim(system_family)                                              as system_family,
        trim(interconnect_family)                                        as interconnect_family,
        trim(interconnect)                                               as interconnect,

        source_file,
        _loaded_at

    from deduplicated
    where _row_num = 1

),

vendors as (

    select * from {{ ref('vendor_mapping') }}

)

select
    typed.*,
    coalesce(
        full_match.vendor_group,
        primary_match.vendor_group,
        typed.manufacturer_primary
    )                                                                    as vendor_group,
    coalesce(full_match.vendor_group, primary_match.vendor_group)
        is not null                                                      as is_vendor_mapped

from typed
left join vendors as full_match
    on full_match.manufacturer_key = typed.manufacturer_key
left join vendors as primary_match
    on primary_match.manufacturer_key = typed.manufacturer_primary_key
