# PostgreSQL 16 + PostGIS 3 + pgvector, the extensions Aurora offers (PRD 7.2).
# Both come from the PGDG apt repo the official image already trusts. Not postgis/postgis:16-*:
# it is built on Debian bullseye, which PGDG no longer serves.
FROM postgres:18.4-trixie
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-postgis-3 postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
