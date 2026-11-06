-- Les coûts mensuels doivent être positifs ou nuls.
-- Anomalie injectée : 4 coûts négatifs (avoirs mal saisis). Signalés, filtrés dans fct_costs_monthly.
{{ config(severity='warn') }}

select project_id, cost_month, cost_eur
from {{ ref('stg_costs') }}
where cost_eur < 0
