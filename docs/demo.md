# Script de démo (10 minutes)

Préparation (avant l'entretien) : `make demo` une première fois (images construites),
navigateur ouvert sur Swagger et sur la doc dbt, terminal dans le dossier du projet.

## 1. Le besoin (1 min)

> « Une direction des opérations HPC a besoin d'un point unique de vérité sur son
> portefeuille — livraisons, budgets, incidents — et d'une vision marché. J'ai construit un
> mini Enterprise Data Hub avec la stack du poste : PostgreSQL, dbt, DuckDB, FastAPI, Docker. »

Montrer le schéma Mermaid du README.

## 2. Tout se lance en une commande (1 min)

```bash
make demo
```

Commenter la sortie : 60 projets, 54,8 % livrés à l'heure, 18,6 jours de retard moyen,
13 projets en dépassement de plus de 5 %, la météo à +11,8 % sur son budget.

## 3. Ingestion robuste (1 min 30)

- TOP500 : vraies listes officielles, formats variables absorbés (`top500_parser.py`).
- Idempotence : relancer `make pipeline` → mêmes volumes ; montrer `meta.load_log` :

```bash
docker compose exec postgres psql -P pager=off -U hub -d hpc_hub \
  -c "select target_table, file_name, rows_loaded, status, finished_at from meta.load_log order by load_id desc limit 6"
```

## 4. dbt et qualité (3 min) — le cœur

Ouvrir la doc dbt (`make dbt-docs`) : lignage `raw → staging → intermediate → marts`.

Montrer le tableau du README « Anomalies injectées » puis :

```bash
curl -s localhost:8001/quality/report | python3 -m json.tool | head -40
```

> « J'ai injecté 17 anomalies en 6 familles ; les 6 tests en alerte les retrouvent toutes,
> au nombre près. Elles sont signalées, pas supprimées en silence ; le filtrage est explicite
> dans les marts. »

Anecdote : le test de non-régression des KPI, recalculés en pandas, a révélé que
`greatest(NULL, 0)` vaut 0 en PostgreSQL et faussait le retard moyen.

## 5. API (1 min 30)

Swagger http://localhost:8001/docs :
- `GET /projects/P0015` : un projet à anomalie (`has_valid_dates: false`), jalons, incidents ;
- `GET /projects/P9999` → 404, `page_size=500` → 422 ;
- `GET /top500/vendors` : Bull, 58 systèmes, 10,7 % du Rmax, ~27 GFlops/W.

Point sécurité : rôle `api_reader` en lecture seule, aucun accès à `raw`.

## 6. DuckDB (1 min)

```bash
make analytics
```

> « PostgreSQL reste la référence ; les marts exportés en Parquet permettent l'analyse ad
> hoc sans charger la production : pivot par édition, QUALIFY, médianes. »

## 7. Limites et suite (1 min)

Synthétique, rechargement complet, pas d'auth. Suite : Airflow, catalogue (OpenMetadata),
RBAC et row-level security, modèles incrémentaux et snapshots SCD2.

## Questions probables

| Question | Réponse courte |
|---|---|
| Pourquoi dbt plutôt que des scripts SQL ? | tests, lignage, docs, dépendances et environnements gérés |
| Comment passer à l'échelle ? | modèles incrémentaux, partitionnement, orchestrateur, pool de connexions |
| Gestion d'un nouveau format TOP500 ? | table d'alias + test de parsing ; `assert_top500_has_500_systems` détecte un fichier tronqué |
| Données sensibles ? | RBAC par schéma, row-level security, secrets hors code, rôle API en lecture seule |
