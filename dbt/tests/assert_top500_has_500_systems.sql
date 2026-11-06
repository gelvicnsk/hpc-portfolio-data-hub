-- Chaque édition chargée doit compter exactement 500 systèmes.
-- Détecte un fichier tronqué ou mal parsé. Ignoré pour les fichiers de test (< 50 lignes).

select edition, count(*) as n_systems
from {{ ref('stg_top500') }}
group by edition
having count(*) <> 500 and count(*) >= 50
