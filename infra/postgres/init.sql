-- =====================================================================
-- Initialisation de la base HPC Portfolio Data Hub
--
-- * Docker : exécuté automatiquement au premier démarrage par l'image postgres
--   (monté dans /docker-entrypoint-initdb.d/), en tant que POSTGRES_USER.
-- * À la main / CI : psql -v ON_ERROR_STOP=1 -f infra/postgres/init.sql
--
-- Le mot de passe du rôle API est lu dans la variable d'environnement
-- API_DB_PASSWORD (\getenv, psql >= 15) : aucun secret dans ce fichier.
-- Script rejouable (idempotent).
-- =====================================================================

\set ON_ERROR_STOP on

\getenv api_password API_DB_PASSWORD
\if :{?api_password}
\else
    DO $$ BEGIN RAISE EXCEPTION 'Variable d''environnement API_DB_PASSWORD manquante'; END $$;
\endif

-- ---------------------------------------------------------------------
-- 1. Schémas : une couche = un schéma
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS raw;           -- données brutes chargées par le pipeline Python
CREATE SCHEMA IF NOT EXISTS staging;       -- dbt : typage, renommage, dédoublonnage
CREATE SCHEMA IF NOT EXISTS intermediate;  -- dbt : jointures métier
CREATE SCHEMA IF NOT EXISTS marts;         -- dbt : tables exposées (API, DuckDB)
CREATE SCHEMA IF NOT EXISTS meta;          -- métadonnées techniques : journal, qualité

-- ---------------------------------------------------------------------
-- 2. Journal des chargements (alimenté par pipeline/ingest/loader.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.load_log (
    load_id        BIGSERIAL PRIMARY KEY,
    source         TEXT        NOT NULL,              -- 'portfolio' | 'top500'
    target_table   TEXT        NOT NULL,              -- ex. 'raw.projects'
    file_name      TEXT,
    rows_loaded    INTEGER,
    status         TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'success', 'failed')),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    error_message  TEXT
);

CREATE INDEX IF NOT EXISTS load_log_target_started_idx
    ON meta.load_log (target_table, started_at DESC);

-- ---------------------------------------------------------------------
-- 3. Résultats des tests dbt (alimenté par pipeline/quality.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.dbt_test_results (
    id               BIGSERIAL PRIMARY KEY,
    invocation_id    TEXT        NOT NULL,            -- identifiant du run dbt
    generated_at     TIMESTAMPTZ NOT NULL,
    unique_id        TEXT        NOT NULL,            -- ex. test.hpc_hub.unique_stg_projects_project_id.abc123
    test_name        TEXT        NOT NULL,
    attached_node    TEXT,                            -- modèle testé
    column_name      TEXT,
    severity         TEXT,                            -- 'error' | 'warn'
    status           TEXT        NOT NULL,            -- 'pass' | 'warn' | 'fail' | 'error' | 'skipped'
    failures         INTEGER,
    message          TEXT,
    execution_time_s NUMERIC(10, 3),
    loaded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (invocation_id, unique_id)
);

-- Dernier run uniquement : c'est ce que lit GET /quality/report
CREATE OR REPLACE VIEW meta.v_latest_test_results AS
SELECT r.*
FROM meta.dbt_test_results AS r
WHERE r.invocation_id = (
    SELECT invocation_id
    FROM meta.dbt_test_results
    ORDER BY generated_at DESC
    LIMIT 1
);

-- ---------------------------------------------------------------------
-- 4. Rôle API en lecture seule (moindre privilège)
--    L'API ne voit que marts + la vue qualité, jamais raw/staging.
-- ---------------------------------------------------------------------
SELECT 'CREATE ROLE api_reader'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'api_reader')
\gexec

ALTER ROLE api_reader WITH LOGIN PASSWORD :'api_password';
ALTER ROLE api_reader SET default_transaction_read_only = on;

SELECT format('GRANT CONNECT ON DATABASE %I TO api_reader', current_database())
\gexec

GRANT USAGE ON SCHEMA marts, meta TO api_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA marts TO api_reader;
-- dbt recrée les tables à chaque run : les droits par défaut s'appliquent aux nouvelles
ALTER DEFAULT PRIVILEGES IN SCHEMA marts GRANT SELECT ON TABLES TO api_reader;

GRANT SELECT ON meta.v_latest_test_results, meta.dbt_test_results, meta.load_log TO api_reader;
