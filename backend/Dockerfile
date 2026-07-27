# Python 3.11 : version stable la mieux supportée par Maigret et ses dépendances.
FROM python:3.11-slim

# Dépendances système :
#  - build-essential : compilation de certaines roues Python
#  - libpq5          : client PostgreSQL pour psycopg
#  - git             : certaines dépendances de Maigret le requièrent à l'installation
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq5 git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Couche de dépendances séparée : le cache Docker évite de tout réinstaller à chaque modification du code
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

COPY . .

RUN mkdir -p /app/donnees && \
    useradd -m -u 1000 searcher && chown -R searcher:searcher /app
USER searcher

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
