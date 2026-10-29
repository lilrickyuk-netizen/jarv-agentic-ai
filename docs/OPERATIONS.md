# JARV operations: self-healing, containers, backups

This is how JARV watches and repairs itself, and how its database is backed up
and restored.

## Container operations

JARV inspects and restarts its own services through `docker-proxy`
(`tecnativa/docker-socket-proxy`), never through the raw Docker socket.

- The proxy allows container list, inspect and logs, plus restart. Everything
  else (images, exec, volumes, networks, creating containers, any other write)
  is denied (`POST=0`).
- The proxy sits on the internal `jarv-ops` network. Only `backend` and
  `worker` join that network, and no port is published to the host.
- JARV restarts only its own Compose project's services in
  `RESTARTABLE`: backend, worker, scheduler, dashboard, local-runner,
  cloud-runner, voicebox, prometheus, grafana, alertmanager.
- `postgres`, `redis` and `docker-proxy` are never restarted automatically.
- A container never restarts itself. The API restarts the worker and the
  worker restarts the API.
- With replicas, only the unhealthy containers of a service are restarted.

Every restart is recorded. An agent restart goes in as a ToolRun plus an audit
entry. A dashboard restart goes in as an audit entry with the operator and the
reason.

## Who can do what

| Action | Tool | Gate |
| --- | --- | --- |
| Health, queue, errors, logs, metrics, server, containers | `check_*`, `query_metrics`, `inspect_server` | Authority 1–2 |
| Uptime of a public URL (private addresses refused) | `check_uptime` | Authority 5 |
| Re-queue missions whose worker died | `recover_stuck_missions` | Authority 4 |
| Restart a JARV service | `restart_service`, `restart_container` | Authority 7 (production repair), no approval |
| Back up the database | `create_backup` | Authority 4 |
| Verify, list backups | `verify_backup`, `list_backups` | Authority 2 |
| Restore a backup (into a new database) | `restore_backup_with_boundary` | Richard's approval |
| Delete expired backups | `cleanup_backups` | Richard's approval |

The monitoring agent observes only. The self-healing agent diagnoses, then
repairs what the evidence shows: stuck missions, or a crashed or unhealthy
service. It verifies each repair with a fresh health check. Code faults are
handed to the debugging agent.

## Backups

- Backups run every `BACKUP_INTERVAL_HOURS` (default 24). They are scheduled by
  Celery beat and run on the worker. Each one is verified straight after.
  "Back up now" on the Infrastructure page takes one on demand.
- Each backup is a `pg_dump` custom-format archive in the `backups` volume
  (`/data/backups`). It is recorded as a BackupRecord with its SHA-256 checksum
  and is kept for `BACKUP_RETENTION_DAYS`.
- Verification has three checks: the file exists, the checksum matches, and
  `pg_restore --list` reads the archive.
- The backend image ships the PostgreSQL 17 client, which can dump any server
  up to 17. A backup is refused when the client is older than the server.

Copy backups off the machine regularly:

```bash
docker run --rm -v jarv-agentic-ai_backups:/data/backups -v "$PWD":/out alpine \
  sh -c 'cp /data/backups/*.dump /out/'
```

## Restoring

A restore always goes into a **new** database named `jarv_restore_<timestamp>`.
The live database is never overwritten.

1. JARV (or you) requests `restore_backup_with_boundary`, and Richard approves it.
2. JARV verifies the archive, creates the new database, and runs `pg_restore`
   into it.
3. Check the restored data:
   ```bash
   docker exec -it jarv-postgres psql -U jarv -d jarv_restore_<timestamp>
   ```
4. To switch JARV over, set `POSTGRES_DB=jarv_restore_<timestamp>` (or
   `DATABASE_URL`) and run `docker compose up -d backend worker scheduler`.
   This is a deliberate operator step.

## Settings

| Setting | Where it is set | Purpose |
| --- | --- | --- |
| `DOCKER_OPS_URL` | compose (backend, worker) | Docker proxy address. Empty disables container operations. |
| `BACKUP_DIR` | compose (backend, worker) | Where backups are written. |
| `PROMETHEUS_URL` | `docker-compose.monitoring.yml` | Prometheus address for `check_health` and `query_metrics`. |
| `JARV_API_URL` | compose (worker) | How the worker reaches the API's `/health`. |
| `BACKUP_INTERVAL_HOURS`, `BACKUP_RETENTION_DAYS` | `.env` | Backup schedule and retention. |
