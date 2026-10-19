#!/bin/sh
# Aurora PostgreSQL as SecondChance finds it right after `terraform apply`: TLS required, a master
# user that is not a superuser (rds_superuser may create roles, databases and these extensions)
# and the rds_iam role it grants. `trust` stands in for IAM authentication: Aurora verifies the
# token, here any password passes, but the client still signs one and must connect over TLS.
set -eu

cat > "$PGDATA/pg_hba.conf" <<'HBA'
local     all all              trust
hostssl   all all 0.0.0.0/0    trust
hostssl   all all ::/0         trust
hostnossl all all 0.0.0.0/0    reject
hostnossl all all ::/0         reject
HBA

psql -v ON_ERROR_STOP=1 --username postgres <<'SQL'
CREATE ROLE rds_iam NOLOGIN;
CREATE ROLE secondchance_master LOGIN CREATEROLE CREATEDB;
GRANT rds_iam TO secondchance_master WITH ADMIN OPTION;
CREATE DATABASE secondchance OWNER secondchance_master;
\connect secondchance
CREATE EXTENSION postgis;
CREATE EXTENSION vector;
SQL
