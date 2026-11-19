#!/bin/bash
# Writes PgBouncer's user list from the environment (never to the image or the repository), then runs PgBouncer.
set -euo pipefail
umask 077
{
  printf '"%s" "%s"\n' myco_global "$MYCO_DEV_GLOBAL_DB_PASSWORD"
  printf '"%s" "%s"\n' myco_cell_c0001 "$MYCO_DEV_CELL_DB_PASSWORD"
  printf '"%s" "%s"\n' keycloak "$MYCO_DEV_KEYCLOAK_DB_PASSWORD"
} > /tmp/userlist.txt
exec pgbouncer /etc/pgbouncer/pgbouncer.ini
