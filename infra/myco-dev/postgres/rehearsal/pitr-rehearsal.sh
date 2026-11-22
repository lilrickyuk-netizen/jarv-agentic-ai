#!/bin/bash
# MYCO's point-in-time-recovery rehearsal (Phase 2 test "PITR rehearsal"), run by the myco-pitr container.
#
# 1. writes a row, takes a fresh base backup of myco-postgres over the replication protocol;
# 2. writes a row to keep, notes the time, writes a row that must NOT come back, and closes the WAL segment so the
#    server archives it (archive_command copies every segment into the WAL archive volume);
# 3. restores the base backup in this container with the archived WAL up to the noted time, promotes it, and reads
#    the rows back: the kept row must be there and the later row absent.
#
# Exit 0 and "PITR REHEARSAL PASS" only when the restore stops exactly at the noted time. Nothing is changed on the
# real server except the rehearsal's own scratch table; the restored copy lives in this container and is discarded.
set -euo pipefail

export PGHOST=myco-postgres PGPORT=5432 PGUSER=myco_backup PGDATABASE=myco_pitr_rehearsal
export PGPASSWORD="$MYCO_DEV_BACKUP_DB_PASSWORD"
WORK=/tmp/pitr
ARCHIVE=/wal-archive
RESTORE_PORT=5499
RUN="run-$(date +%s)-$$"

say() { echo "[pitr $(date -u +%H:%M:%S)] $*"; }
fail() { echo "PITR REHEARSAL FAIL: $*"; exit 1; }
trap 'echo "PITR REHEARSAL FAIL: the step at line $LINENO stopped with an error"' ERR

for _ in $(seq 1 60); do pg_isready -q && break; sleep 2; done
pg_isready -q || fail "myco-postgres did not answer"

rm -rf "$WORK" && mkdir -p "$WORK"
psql -v ON_ERROR_STOP=1 -qc "CREATE TABLE IF NOT EXISTS rehearsal (run text NOT NULL, step text NOT NULL,
                               at timestamptz NOT NULL DEFAULT clock_timestamp())"
psql -v ON_ERROR_STOP=1 -qc "INSERT INTO rehearsal (run, step) VALUES ('$RUN', 'before-backup')"

say "taking a base backup"
pg_basebackup -D "$WORK/data" -X stream -c fast -l "myco-pitr-$RUN" >/dev/null || fail "pg_basebackup failed"

psql -v ON_ERROR_STOP=1 -qc "INSERT INTO rehearsal (run, step) VALUES ('$RUN', 'kept')"
sleep 1
TARGET=$(psql -Atc "SELECT clock_timestamp()")
sleep 1
psql -v ON_ERROR_STOP=1 -qc "INSERT INTO rehearsal (run, step) VALUES ('$RUN', 'after-target')"
SEGMENT=$(psql -Atc "SELECT pg_walfile_name(pg_current_wal_lsn())")
psql -Atc "SELECT pg_switch_wal()" >/dev/null || fail "could not close the WAL segment (pg_switch_wal)"
say "target time $TARGET; waiting for $SEGMENT to be archived"
for _ in $(seq 1 60); do [ -f "$ARCHIVE/$SEGMENT" ] && break; sleep 1; done
[ -f "$ARCHIVE/$SEGMENT" ] || fail "WAL segment $SEGMENT was not archived within 60 seconds (archive_command)"

# A restored copy refuses to recover with fewer of these than the server it came from had (PostgreSQL checks them
# against the WAL), so it is started with the server's own values.
MATCH=""
for setting in max_connections max_worker_processes max_wal_senders max_prepared_transactions max_locks_per_transaction; do
  MATCH="$MATCH -c $setting=$(psql -Atc "SHOW $setting")"
done
say "restoring to the target time"
chmod 700 "$WORK/data"
touch "$WORK/data/recovery.signal"
cat >> "$WORK/data/postgresql.auto.conf" <<CONF
restore_command = 'cp $ARCHIVE/%f %p'
recovery_target_time = '$TARGET'
recovery_target_action = 'promote'
archive_mode = off
CONF
pg_ctl -D "$WORK/data" -l "$WORK/restore.log" -w -t 180 \
  -o "-p $RESTORE_PORT -c listen_addresses='' -k $WORK -c shared_buffers=64MB$MATCH" start >/dev/null \
  || { cat "$WORK/restore.log"; fail "the restored copy did not start"; }
for _ in $(seq 1 90); do
  [ "$(psql -h "$WORK" -p "$RESTORE_PORT" -Atc 'SELECT pg_is_in_recovery()' 2>/dev/null)" = "f" ] && break
  sleep 1
done
STEPS=$(psql -h "$WORK" -p "$RESTORE_PORT" -Atc \
  "SELECT string_agg(step, ',' ORDER BY at) FROM rehearsal WHERE run = '$RUN'")
pg_ctl -D "$WORK/data" -m fast -w stop >/dev/null || true

[ "$STEPS" = "before-backup,kept" ] || fail "restored rows were '$STEPS', expected 'before-backup,kept'"

# Segments older than this backup's start are no use to any backup this stack keeps.
# (After recovery PostgreSQL keeps the backup's label as backup_label.old.)
LABEL="$WORK/data/backup_label.old"
[ -f "$LABEL" ] || LABEL="$WORK/data/backup_label"
START=""
[ -f "$LABEL" ] && START=$(sed -n 's/^START WAL LOCATION: .*(file \([0-9A-F]\{24\}\)).*/\1/p' "$LABEL" | head -1)
if [ -n "$START" ]; then pg_archivecleanup "$ARCHIVE" "$START" || say "old WAL segments were left in place"; fi
rm -rf "$WORK"
echo "PITR REHEARSAL PASS: restored myco-postgres to $TARGET from a base backup and the archived WAL; the row written before it is back and the row written after it is not."
