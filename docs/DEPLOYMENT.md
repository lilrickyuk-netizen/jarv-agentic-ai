# Deploying projects to your VPS

JARV deploys a workspace project to your server over SSH. On the server it runs
the project's Docker Compose file. There are two environments, `staging` and
`production`, kept as separate Compose projects on the same server.

## How a release works

1. **Package.** JARV takes the committed code at `HEAD` of the workspace
   repository (`git archive`). It refuses to deploy if there are uncommitted
   changes, so every release matches a commit.
2. **Upload.** The code goes to `/srv/jarv/<app>-<env>/releases/<release id>`.
   The server's `/srv/jarv/<app>-<env>/shared/.env` is linked into the release.
   The app's secrets live only on the server, never in git or in JARV.
3. **Start.** JARV runs `docker compose -p <app>-<env> up -d --build --remove-orphans`.
4. **Health check.** JARV polls the app's health URL until it answers below 500.
   - **Pass:** `current` switches to the new release, and the newest 5
     releases are kept.
   - **Fail** (or the build or start fails): the previous release is brought
     back up, the failed release is deleted, and the deployment is recorded as
     rolled back.

| Tool | What it does | Gate |
| --- | --- | --- |
| `check_deploy_target` | Checks the server is configured and reachable | Authority 1 |
| `deploy_staging` | Deploys to staging | Authority 7, no approval |
| `deploy_production_with_boundary` | Releases to production | **Richard's approval, every time** |
| `rollback` | Returns to the previous (or a named) release, health-checked | Authority 7, recorded with the reason |
| `deployment_status`, `deployment_logs` | Shows releases, the current release, containers and logs | Authority 2 |

Every deploy and rollback is stored as a DeploymentRecord. Each record holds
the commit, the release, the previous release, the health result, the full
log, and any error.

## One-time server setup

These steps use a fresh Ubuntu 24.04 VPS.

1. **Create the deploy user and install Docker** (run on the server as root):
   ```bash
   curl -fsSL https://get.docker.com | sh
   adduser --disabled-password --gecos "" deploy
   usermod -aG docker deploy
   mkdir -p /srv/jarv && chown deploy:deploy /srv/jarv
   ```
2. **Make a dedicated deploy key** (run on your PC, in WSL). Use this key for
   JARV only, never your personal key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/jarv_deploy -N "" -C "jarv-deploy"
   ssh-copy-id -i ~/.ssh/jarv_deploy.pub deploy@YOUR_SERVER_IP
   ```
3. **Pin the server's host key**, so JARV only ever connects to this server:
   ```bash
   ssh-keyscan -t ed25519 YOUR_SERVER_IP
   ```
4. **Give JARV the settings.** Add these lines to `apps/backend/.env`. That file
   is git-ignored and never committed.
   ```bash
   DEPLOY_SSH_HOST=YOUR_SERVER_IP
   DEPLOY_SSH_USER=deploy
   DEPLOY_SSH_PRIVATE_KEY=<output of: base64 -w0 ~/.ssh/jarv_deploy>
   DEPLOY_SSH_KNOWN_HOSTS=<the line printed by ssh-keyscan>
   ```
   Then restart JARV's backend and worker:
   ```bash
   docker compose up -d backend worker
   ```
5. **Put each app's secrets on the server**, once per app and environment:
   ```bash
   ssh -i ~/.ssh/jarv_deploy deploy@YOUR_SERVER_IP
   mkdir -p /srv/jarv/myco-staging/shared
   nano /srv/jarv/myco-staging/shared/.env
   ```
6. **Point the workspace at its health URLs.** Set this in the workspace's
   settings (`config.deploy`):
   ```json
   {"app": "myco", "compose_file": "docker-compose.yml",
    "health_url": {"staging": "https://staging.myco.example/health",
                   "production": "https://myco.example/health"}}
   ```
   A `http://localhost:PORT/...` health URL is checked from the server itself.
   Use that form when the app isn't public yet.

Ask JARV to "check the deploy target" to confirm the setup. Putting the key on
the server and approving production releases are the only steps that need you.
