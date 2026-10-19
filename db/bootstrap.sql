-- Cluster bootstrap, run once by the postgres superuser on an empty data directory
-- (docker-entrypoint-initdb.d). Tables come from Alembic, not from here.
-- On Aurora the same roles are created by the P4 bootstrap, with IAM auth instead of passwords.

\getenv migrator_password SECONDCHANCE_MIGRATOR_PASSWORD
\getenv app_password SECONDCHANCE_APP_PASSWORD
\getenv maintenance_password SECONDCHANCE_MAINTENANCE_PASSWORD

-- Runs Alembic and owns the tables. Not a superuser.
CREATE ROLE secondchance_migrator LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS PASSWORD :'migrator_password';

-- Used by the API. Owns nothing and has no BYPASSRLS, so every RLS policy applies (ADR-003).
CREATE ROLE secondchance_app LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS PASSWORD :'app_password';
-- A stuck transaction must not hold an offer's row lock forever.
ALTER ROLE secondchance_app SET statement_timeout = '10s';
ALTER ROLE secondchance_app SET lock_timeout = '5s';
ALTER ROLE secondchance_app SET idle_in_transaction_session_timeout = '30s';

-- Scheduled jobs only (retention, GDPR erasure, re-queueing stuck work). It crosses tenants
-- through policies written TO this role (migration 0005), never through BYPASSRLS, and the
-- migrations grant it nothing beyond SELECT and DELETE on the tables those jobs touch.
CREATE ROLE secondchance_maintenance LOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS PASSWORD :'maintenance_password';
ALTER ROLE secondchance_maintenance SET statement_timeout = '60s';

-- Database owner = migrator, so it can create objects in the public schema (PG 15+).
ALTER DATABASE secondchance OWNER TO secondchance_migrator;
CREATE DATABASE secondchance_test OWNER secondchance_migrator;
-- No temp tables: on a pooled connection one would shadow the real table of the same name.
REVOKE TEMPORARY ON DATABASE secondchance, secondchance_test FROM PUBLIC;

-- Extensions need a superuser, so they live here rather than in a migration.
\connect secondchance
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;

\connect secondchance_test
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
