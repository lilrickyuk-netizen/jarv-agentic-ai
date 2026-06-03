# Railway Deployment Guide

Deploy JARV to Railway with simple Docker-based deployment. Railway offers $5/month free credit and pay-as-you-go pricing.

## Cost Estimate

Railway charges based on usage (CPU, RAM, Network):
- **Starter Plan**: $5/month included credit
- **Typical JARV Usage**: $15-25/month after free credit
- **Resources**: Scales automatically based on load

## Prerequisites

1. Railway account (railway.app)
2. GitHub repository with JARV code
3. Domain name (optional, Railway provides subdomains)

## Step 1: Create New Project

1. Go to Railway Dashboard (railway.app)
2. Click **New Project**
3. Select **Deploy from GitHub repo**
4. Authorize Railway to access your repository
5. Select your JARV repository

## Step 2: Add PostgreSQL Database

1. In your project, click **New**
2. Select **Database** > **PostgreSQL**
3. Database is automatically provisioned
4. Railway generates connection variables:
   - `PGHOST`
   - `PGPORT`
   - `PGUSER`
   - `PGPASSWORD`
   - `PGDATABASE`
   - `DATABASE_URL`

## Step 3: Add Redis

1. Click **New** > **Database** > **Redis**
2. Redis is automatically provisioned
3. Railway generates `REDIS_URL`

## Step 4: Configure Backend Service

1. In project, click **New** > **GitHub Repo**
2. Select your JARV repository
3. Settings:
   - Name: `backend`
   - Root Directory: `apps/backend`
   - Build Command: `docker build -f Dockerfile -t backend .`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4`
4. Environment Variables (automatically generated + custom):
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   REDIS_URL=${{Redis.REDIS_URL}}
   SECRET_KEY=<Generate strong key>
   CLAUDE_API_KEY=<Your Claude API key>
   OPENAI_API_KEY=<Your OpenAI API key>
   GEMINI_API_KEY=<Your Gemini API key>
   ENVIRONMENT=production
   LOG_LEVEL=INFO
   PORT=8000
   ```
5. Click **Deploy**

### Generate Public URL for Backend

1. Go to backend service settings
2. Click **Generate Domain**
3. Railway provides: `backend-production-xxxx.up.railway.app`
4. **Save this URL**

## Step 5: Configure Dashboard Service

1. Click **New** > **GitHub Repo**
2. Select your JARV repository
3. Settings:
   - Name: `dashboard`
   - Root Directory: `apps/dashboard`
   - Build Command: `docker build -f Dockerfile -t dashboard .`
   - Start Command: `node server.js`
4. Environment Variables:
   ```
   NEXT_PUBLIC_API_URL=https://backend-production-xxxx.up.railway.app
   NODE_ENV=production
   PORT=3000
   ```
5. Click **Deploy**
6. Generate public domain for dashboard

## Step 6: Add Celery Worker

1. Click **New** > **GitHub Repo**
2. Select your JARV repository
3. Settings:
   - Name: `worker`
   - Root Directory: `apps/backend`
   - Build Command: `docker build -f Dockerfile -t worker .`
   - Start Command: `celery -A app.workers.celery_app worker --loglevel=info --concurrency=2`
4. Environment Variables: Same as backend (references are auto-linked)
5. **Disable** public domain (worker doesn't need external access)
6. Click **Deploy**

## Step 7: Add Celery Beat Scheduler

1. Click **New** > **GitHub Repo**
2. Select your JARV repository
3. Settings:
   - Name: `scheduler`
   - Root Directory: `apps/backend`
   - Build Command: `docker build -f Dockerfile -t scheduler .`
   - Start Command: `celery -A app.workers.celery_app beat --loglevel=info`
4. Environment Variables: Same as backend
5. **Disable** public domain
6. Click **Deploy**

## Step 8: Run Database Migrations

Railway doesn't have a shell interface, so run migrations via a temporary service:

### Option 1: One-off Command (Recommended)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login
railway login

# Link to project
railway link

# Run migrations
railway run -s backend alembic upgrade head
railway run -s backend python -m app.scripts.setup_admin
```

### Option 2: Initialization Service

Create a temporary service that runs migrations once:

1. Click **New** > **GitHub Repo**
2. Settings:
   - Name: `init`
   - Root Directory: `apps/backend`
   - Start Command: `alembic upgrade head && python -m app.scripts.setup_admin && sleep infinity`
3. After it completes, delete this service

## Step 9: Update CORS Origins

Update backend environment variables with dashboard domain:

```
CORS_ORIGINS=https://dashboard-production-xxxx.up.railway.app
```

Redeploy backend service.

## Step 10: Custom Domain (Optional)

### Add Custom Domain to Dashboard

1. Go to dashboard service settings
2. Click **Settings** > **Domains**
3. Click **Custom Domain**
4. Enter: `jarv.yourdomain.com`
5. Add CNAME record to your DNS:
   ```
   jarv.yourdomain.com CNAME dashboard-production-xxxx.up.railway.app
   ```
6. SSL certificate is automatically provisioned

### Add Custom Domain to Backend

1. Go to backend service settings
2. Add custom domain: `api.yourdomain.com`
3. Add CNAME record to DNS
4. Update dashboard environment variable:
   ```
   NEXT_PUBLIC_API_URL=https://api.yourdomain.com
   ```
5. Update backend CORS_ORIGINS

## Step 11: Access JARV

Your JARV instance is now running:
- Dashboard: `https://dashboard-production-xxxx.up.railway.app`
- API: `https://backend-production-xxxx.up.railway.app`

## Auto-Deploy on Git Push

Railway automatically redeploys when you push to your main branch:

```bash
git add .
git commit -m "Update JARV"
git push origin main
```

All services will automatically update.

## Monitoring

### View Logs

```bash
# Using Railway CLI
railway logs -s backend
railway logs -s worker
railway logs -s dashboard
```

### View Metrics

1. Go to service in dashboard
2. Click **Metrics** tab
3. View CPU, Memory, Network usage

### Set Up Alerts

1. Service settings > **Observability**
2. Configure alerts for:
   - High CPU usage
   - High memory usage
   - Service crashes

## Backup Database

### Manual Backup

```bash
# Using Railway CLI
railway run -s postgres pg_dump $DATABASE_URL > backup.sql
```

### Automated Backups

Railway doesn't provide automatic backups. Use a scheduled job:

1. Create backup script in repository: `scripts/backup.sh`
2. Add cron service using Railway
3. Or use external service like GitHub Actions

## Scaling

### Vertical Scaling (Resources)

Railway automatically scales resources based on usage. You can set limits:

1. Service settings > **Resources**
2. Set CPU/Memory limits
3. Set restart policy

### Horizontal Scaling (Replicas)

Railway Pro plan supports replicas:

1. Service settings > **Replicas**
2. Set number of instances
3. Railway handles load balancing

## Troubleshooting

### Service Won't Start

```bash
# Check logs
railway logs -s backend

# Check build logs
railway logs -s backend --type build
```

### Out of Memory

1. Check metrics to confirm
2. Optimize code or increase memory limits
3. Consider splitting services

### Database Connection Issues

```bash
# Verify database is running
railway status -s postgres

# Check DATABASE_URL variable
railway variables -s backend
```

## Cost Optimization

### Monitor Usage

1. Go to project settings
2. Click **Usage**
3. View current month's cost breakdown

### Optimize Resources

- **Reduce worker concurrency** if CPU usage is high
- **Use environment variables** to disable unnecessary features
- **Implement caching** to reduce database queries
- **Scale down** during low-traffic periods

### Free Trial

Railway provides $5/month free credit. Typical JARV usage:
- First month: Free (with $5 credit)
- Subsequent months: $15-25/month

For free deployment, use Oracle Cloud Always Free ($0/month).

## Railway CLI Commands

```bash
# Install
npm i -g @railway/cli

# Login
railway login

# Link project
railway link

# View services
railway status

# View logs
railway logs -s <service>

# Run command
railway run -s <service> <command>

# Open in browser
railway open
```

## Advantages of Railway

✅ Simple deployment process
✅ Automatic SSL certificates
✅ Auto-deploy from Git
✅ Built-in PostgreSQL and Redis
✅ Good developer experience
✅ Automatic resource scaling

## Disadvantages

❌ More expensive than Oracle Cloud
❌ No permanent free tier
❌ Less control over infrastructure
❌ $5/month minimum after free credit

For zero-cost production deployment, use Oracle Cloud Always Free instead.
