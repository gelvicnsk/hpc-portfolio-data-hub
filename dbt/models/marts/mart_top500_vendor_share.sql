-- Parts de marché des constructeurs dans le TOP500, par édition.
-- Grain : 1 ligne par (édition, groupe constructeur), y compris les éditions où un
-- constructeur est absent (0 système) pour calculer correctement l'évolution.

with systems as (

    select * from {{ ref('stg_top500') }}

),

editions as (

    select distinct edition, edition_date from systems

),

vendors as (

    select distinct vendor_group from systems

),

per_vendor as (

    select
        edition,
        vendor_group,
        count(*)                                                    as n_systems,
        sum(rmax_tflops)                                            as rmax_tflops,
        count(*) filter (where has_power_data)                      as n_systems_with_power,
        sum(rmax_tflops) filter (where has_power_data)              as rmax_tflops_with_power,
        sum(power_kw) filter (where has_power_data)                 as power_kw,
        min(rank)                                                   as best_rank
    from systems
    group by edition, vendor_group

),

grid as (

    select
        editions.edition,
        editions.edition_date,
        vendors.vendor_group,
        coalesce(per_vendor.n_systems, 0)                           as n_systems,
        coalesce(per_vendor.rmax_tflops, 0)                         as rmax_tflops,
        coalesce(per_vendor.n_systems_with_power, 0)                as n_systems_with_power,
        per_vendor.rmax_tflops_with_power,
        per_vendor.power_kw,
        per_vendor.best_rank
    from editions
    cross join vendors
    left join per_vendor
        on per_vendor.edition = editions.edition
        and per_vendor.vendor_group = vendors.vendor_group

),

shares as (

    select
        *,
        round(100.0 * n_systems / sum(n_systems) over (partition by edition), 2)
                                                                    as share_systems_pct,
        round(100.0 * rmax_tflops / sum(rmax_tflops) over (partition by edition), 2)
                                                                    as share_rmax_pct
    from grid

),

final as (

    select
        edition || '-' || vendor_group                              as vendor_share_id,
        edition,
        edition_date,
        vendor_group,
        n_systems,
        share_systems_pct,
        round(rmax_tflops / 1000, 1)                                as rmax_pflops,
        share_rmax_pct,
        rank() over (partition by edition order by n_systems desc)  as rank_by_systems,
        rank() over (partition by edition order by rmax_tflops desc) as rank_by_rmax,
        best_rank                                                   as best_system_rank,
        n_systems_with_power,
        -- efficacité agrégée : Rmax total / puissance totale des systèmes qui la déclarent
        round(rmax_tflops_with_power / nullif(power_kw, 0), 2)      as energy_efficiency_gflops_w,
        share_systems_pct - lag(share_systems_pct) over w           as share_systems_change_pts,
        share_rmax_pct - lag(share_rmax_pct) over w                 as share_rmax_change_pts,
        lag(n_systems) over w                                       as previous_n_systems
    from shares
    window w as (partition by vendor_group order by edition_date)

)

-- on garde les absences seulement juste après une présence (sortie du classement)
select * from final
where n_systems > 0 or previous_n_systems > 0
