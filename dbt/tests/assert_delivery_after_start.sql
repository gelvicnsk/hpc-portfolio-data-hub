-- Une livraison ne peut pas précéder le démarrage du projet.
-- Anomalie injectée : 2 projets. Signalés, exclus des KPI de délai dans fct_project_delivery.
{{ config(severity='warn') }}

select project_id, start_date, actual_delivery_date
from {{ ref('stg_projects') }}
where actual_delivery_date < start_date
