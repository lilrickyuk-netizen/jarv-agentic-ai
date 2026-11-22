#!/bin/bash
# MYCO's local development PostgreSQL (spec section 36.1 and Phase 2, local-development mapping): one server process
# holds the three database authorities as separate logical databases, each owned by its own role, and no role can
# connect to another authority's database. Runs once, when the data volume is new (the official image's
# docker-entrypoint-initdb.d). Passwords come from the environment the installer writes; none is in this file.
#
#   keycloak               Keycloak's own database (Keycloak alone writes it; Phase 3)
#   myco_global            Global Control PostgreSQL authority (routing, organisations, billing metadata)
#   myco_cell_local_c0001  the first Platform Cell, local-c0001 (project engineering state)
#   temporal, temporal_visibility   Temporal's persistence (Temporal's setup builds their tables)
#   myco_pitr_rehearsal    the point-in-time-recovery rehearsal's scratch database (myco_backup)
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v keycloak_pw="$MYCO_DEV_KEYCLOAK_DB_PASSWORD" \
  -v global_pw="$MYCO_DEV_GLOBAL_DB_PASSWORD" \
  -v cell_pw="$MYCO_DEV_CELL_DB_PASSWORD" \
  -v temporal_pw="$MYCO_DEV_TEMPORAL_DB_PASSWORD" \
  -v backup_pw="$MYCO_DEV_BACKUP_DB_PASSWORD" <<'SQL'
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_pw';
CREATE ROLE myco_global LOGIN PASSWORD :'global_pw';
CREATE ROLE myco_cell_c0001 LOGIN PASSWORD :'cell_pw';
CREATE ROLE temporal LOGIN CREATEDB PASSWORD :'temporal_pw';
CREATE ROLE myco_backup LOGIN REPLICATION PASSWORD :'backup_pw';

CREATE DATABASE keycloak OWNER keycloak;
CREATE DATABASE myco_global OWNER myco_global;
CREATE DATABASE myco_cell_local_c0001 OWNER myco_cell_c0001;
CREATE DATABASE myco_pitr_rehearsal OWNER myco_backup;
-- Temporal's two databases, made here so its setup only builds their tables (SKIP_DB_CREATE in docker-compose.yml).
CREATE DATABASE temporal OWNER temporal;
CREATE DATABASE temporal_visibility OWNER temporal;

-- Each authority is reachable only by its owner: no cross-authority connection, so no cross-cell SQL.
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
REVOKE ALL ON DATABASE myco_global FROM PUBLIC;
REVOKE ALL ON DATABASE myco_cell_local_c0001 FROM PUBLIC;
REVOKE ALL ON DATABASE myco_pitr_rehearsal FROM PUBLIC;
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;
-- Temporal's setup tool connects to "postgres" to create its two databases.
GRANT CONNECT ON DATABASE postgres TO temporal;

-- The rehearsal closes a WAL segment so it is archived before it restores. Function rights are per database, so
-- the grant is made in the rehearsal's own database, where it calls it.
\connect myco_pitr_rehearsal
GRANT EXECUTE ON FUNCTION pg_switch_wal() TO myco_backup;
SQL

# Base backups for the rehearsal stream over the replication protocol, only as myco_backup and only with its password.
echo "host replication myco_backup all scram-sha-256" >> "$PGDATA/pg_hba.conf"
