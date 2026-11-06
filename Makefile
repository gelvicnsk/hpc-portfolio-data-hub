# HPC Portfolio Data Hub — commandes usuelles (« make help » pour la liste)
SHELL := /bin/bash
COMPOSE := docker compose
API_PORT := $(or $(shell grep -E '^API_PORT=' .env 2>/dev/null | cut -d= -f2),8001)
API_URL := http://localhost:$(API_PORT)

.DEFAULT_GOAL := help
.PHONY: help env up demo pipeline logs down reset test lint format dbt-docs analytics clean

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env: ## Crée .env (mots de passe aléatoires) et y renseigne HOST_UID/HOST_GID
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		sed -i "s/^API_DB_PASSWORD=change_me_too$$/API_DB_PASSWORD=$$(openssl rand -hex 16)/" .env; \
		sed -i "s/^POSTGRES_PASSWORD=change_me$$/POSTGRES_PASSWORD=$$(openssl rand -hex 16)/" .env; \
		echo ".env créé avec des mots de passe aléatoires"; \
	fi
	@grep -q '^HOST_UID=' .env || echo "HOST_UID=$$(id -u)" >> .env
	@grep -q '^HOST_GID=' .env || echo "HOST_GID=$$(id -g)" >> .env

up: env ## Construit et lance tout : postgres -> pipeline -> api
	$(COMPOSE) up -d --build

demo: up ## Lance tout puis affiche les KPI principaux via l'API
	@python3 scripts/demo.py $(API_URL)

pipeline: env ## Relance le pipeline (ingestion + dbt + qualité + export)
	$(COMPOSE) run --rm --build pipeline

logs: ## Journaux du pipeline et de l'API
	$(COMPOSE) logs pipeline api --tail 80

down: ## Arrête les conteneurs (les données sont conservées)
	$(COMPOSE) down

reset: ## Arrête tout et SUPPRIME la base (repart de zéro)
	$(COMPOSE) down -v

test: ## Tests Python (intégration si PG_TEST_DSN est défini)
	pytest

lint: ## Vérifie le style (ruff)
	ruff check . && ruff format --check .

format: ## Reformate le code (ruff)
	ruff format . && ruff check --fix .

dbt-docs: env ## Génère et sert la documentation dbt sur http://localhost:8080
	set -a; source .env; set +a; cd dbt && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir . --port 8080

analytics: ## Requêtes DuckDB de démonstration sur les exports Parquet
	python -m pipeline.export_duckdb --no-export --queries analytics/queries.sql

clean: ## Supprime les fichiers générés localement (caches, artefacts dbt, exports)
	rm -rf .pytest_cache .ruff_cache dbt/target dbt/logs data/analytics/*.parquet data/analytics/hub.duckdb
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
