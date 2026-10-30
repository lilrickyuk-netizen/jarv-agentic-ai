# JARV runbook

How to run, use, upgrade and look after JARV. Two companion guides go deeper:

- [DEPLOYMENT.md](DEPLOYMENT.md): how JARV deploys your projects (MYCO and the rest) to your VPS.
- [OPERATIONS.md](OPERATIONS.md): self-healing, container restarts, backups and restores.
- [CONFIGURATION.md](CONFIGURATION.md): every setting.

`BUILD_LEDGER.md` at the repository root records what was built and how it was tested.

---

## 1. What runs

| Service | Role |
| --- | --- |
| `postgres` (pgvector), `redis` | Data and queues. Never restarted automatically. |
| `migrate` | Runs `alembic upgrade head` once, then exits. Everything below waits for it. |
| `backend` | The API (FastAPI): agents, tools, missions, approvals, voice, settings. |
| `worker`, `scheduler` | Mission execution, the daily company loop, backups (Celery and Celery beat). |
| `dashboard` | The web dashboard (Next.js). It calls the backend through its own `/api/backend` proxy. |
| `docker-proxy` | Restricted Docker access for container status and approved restarts. Never the raw socket. |
| `nginx` (production) | TLS, rate limits. `/api/backend/*` goes to the dashboard; the rest of `/api` (Stripe and alert webhooks, calendar feed links, the hands-free wake socket) goes to the backend. |

## 2. Running JARV locally (your PC, WSL)

```bash
cd ~/jarv-agentic-ai
docker compose up -d                 # migrate runs first, then backend, worker, scheduler, dashboard
docker compose ps                    # migrate should show "exited (0)"
```

Open http://localhost:3000 and sign in. Keys for local use go in `apps/backend/.env`
(git-ignored). Restart after changing it: `docker compose up -d backend worker`.

If `migrate` fails with "relation ... already exists", the database was created before migrations
were run automatically. Check that its tables match the current models (the test run does this
against a fresh database), then record it as migrated once:
`docker compose run --rm migrate python -m alembic stamp head`.

## 3. Running JARV on your VPS (production)

One-time:

1. Install Docker on the server (see DEPLOYMENT.md, step 1) and clone the repository.
2. `cp .env.production.example .env.production` and fill it in. At minimum:
   `SECRET_KEY` (`openssl rand -hex 32`), `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`,
   `REDIS_PASSWORD`, `CLAUDE_API_KEY`. Everything else (email, Stripe, Plausible, Slack, voice,
   deployment) can be added later; each service stays switched off until its settings are present.
   `.env.production` is git-ignored: it never leaves the server.
3. TLS certificates: follow `infra/nginx/ssl/README.md` (Let's Encrypt) so that
   `infra/nginx/ssl/cert.pem` and `key.pem` exist.
4. Start:
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
   ```
5. Create your operator account (admin):
   ```bash
   docker compose --env-file .env.production -f docker-compose.prod.yml exec backend \
     python scripts/setup_admin.py --username richard
   ```
6. Sign in at `https://your-domain`, open **Settings** and press **Check** on each configured
   service. Every check is free and read-only; it never sends anything or spends credit.

## 4. Upgrading

```bash
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

`migrate` applies new database migrations before the new backend starts. Take a backup first
("Back up now" on the Infrastructure page) for anything beyond a small change.

## 5. Using JARV

- **Give a mission** in the Command Center (typed or by voice). JARV plans it, hands each step to
  the right specialist agent, and those agents work through their own tools, confined to the
  workspace's folder. Progress and every handoff appear in the mission panel and the Live
  Operations Feed.
- **Hard boundaries pause only the blocked step**: publishing, production releases, spending over
  budget, mass email, binding commitments, deleting production data, account security, and
  anything that weakens safety. Safe steps keep running. Decide on the **Approvals** page (or
  **Richard Boundary Operator**); JARV resumes from its checkpoint when you approve.
- **Talk with JARV** in the voice panel opens a live spoken conversation (OpenAI Realtime, on your
  OpenAI key, billed per minute while open): talk naturally, interrupt it, ask it to do things; work
  it starts runs as missions and it tells you the outcome.
- **Approvals are never taken by voice.** Voice commands become missions under the same gate.
- **Workspaces**: deleting a workspace archives it (reversible). Permanent deletion asks you to
  type the workspace's slug and is written to the audit log.
- **Calendar**: Settings > Calendar subscription gives each workspace a private link to add once
  to Google, Apple or Outlook Calendar; the agents' events then appear there. "New link" retires
  the old one.

## 6. Checking health

- Dashboard: **Settings** (database, Redis, model providers, every service), **Operations** and
  **Infrastructure** (containers, server, backups), **Analytics** (missions, tools, cost).
- Command line:
  ```bash
  curl -fsS https://your-domain/health          # nginx
  docker compose -f docker-compose.prod.yml ps
  docker compose -f docker-compose.prod.yml logs --tail 200 backend worker
  ```
- Optional monitoring stack (Prometheus, Grafana, Alertmanager):
  `docker compose -f docker-compose.monitoring.yml --env-file .env.production up -d`.

## 7. Tests

Backend, in Docker against PostgreSQL 16 with pgvector (never spends provider credit; every key is
blanked in tests). The migrations are checked on one database; the suite runs on a second, fresh one,
because PostgreSQL enforces the foreign keys, column types and lengths that a file database does not.
Run one test run at a time: two runs on the same database delete each other's tables.

```bash
docker build --target test -t jarv-backend-test:latest apps/backend
docker run -d --rm --name jarv-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=jarv_migrations -p 55432:5432 pgvector/pgvector:pg16
sleep 8
docker exec jarv-test-pg psql -U postgres -c "CREATE DATABASE jarv_tests"
docker exec jarv-test-pg psql -U postgres -d jarv_tests -c "CREATE EXTENSION IF NOT EXISTS vector"
docker run --rm --network host -e DATABASE_URL=postgresql://postgres:test@localhost:55432/jarv_migrations \
  -e TESTING=1 -e SECRET_KEY=test-secret-key-for-ci-only-32chars jarv-backend-test:latest python -m alembic upgrade head
docker run --rm --network host -v "$PWD":/repo:ro -e JARV_REPO_ROOT=/repo \
  -e DATABASE_URL=postgresql://postgres:test@localhost:55432/jarv_tests \
  -e TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/jarv_tests -e TESTING=1 \
  -e SECRET_KEY=test-secret-key-for-ci-only-32chars jarv-backend-test:latest \
  sh -c "python -m pytest -q --tb=short -p no:logging -rf"
docker stop jarv-test-pg
```

Dashboard:

```bash
docker run --rm -v "$PWD/apps/dashboard":/src:ro node:20 sh -c \
  "cp -r /src /app && cd /app && npm ci --no-audit --no-fund && npx tsc --noEmit && npx jest --ci"
```

`tests/test_repair15c_final_acceptance.py` is the end-to-end acceptance test: a multi-agent mission
through the API, real file edits and compilation by the agents, a hard-boundary pause, your
approval and the resume.

## 8. When something goes wrong

| Symptom | What to do |
| --- | --- |
| A mission is stuck | JARV re-queues missions whose worker stopped (every minute). Cancel or retry it from the Command Center. |
| A service is unhealthy | The self-healing agent restarts JARV's own services (not postgres, redis or the proxy) and verifies the repair. Or restart it from the Infrastructure page. |
| A provider is out of credit or rate limited | Missions fail over to the next provider in `PROVIDER_ORDER`. Settings shows which have keys; **Check** confirms a key works. |
| Email, Slack or a webhook does nothing | Settings shows what is missing for that service and **Send test notification** proves delivery. |
| VS Code or Docker cannot reach Ubuntu ("Wsl/Service/E_UNEXPECTED") | In Windows PowerShell: `wsl --shutdown`, wait 10 seconds, `wsl -d Ubuntu-24.04`. If that fails, an administrator PowerShell `Restart-Service LxssManager -Force` (or `WSLService`), then `wsl --update` and a reboot. Restart Docker Desktop afterwards. |
| You need data back | Restores go into a new database and need your approval: see OPERATIONS.md. |
