FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # le conteneur tourne avec l'UID de l'utilisateur hôte : HOME doit être inscriptible
    HOME=/tmp \
    DO_NOT_TRACK=1

WORKDIR /app

COPY pyproject.toml ./
COPY pipeline ./pipeline
RUN pip install ".[pipeline]"

# dbt/, data/ et analytics/ sont montés en volume (voir docker-compose.yml) :
# les résultats (Parquet, docs dbt, artefacts) restent sur l'hôte.
CMD ["python", "-m", "pipeline.run"]
