-- Les parts de marché d'une édition doivent totaliser 100 % (à l'arrondi près),
-- en nombre de systèmes comme en Rmax.

select
    edition,
    sum(share_systems_pct) as total_share_systems,
    sum(share_rmax_pct)    as total_share_rmax
from {{ ref('mart_top500_vendor_share') }}
group by edition
having abs(sum(share_systems_pct) - 100) > 0.5
    or abs(sum(share_rmax_pct) - 100) > 0.5
