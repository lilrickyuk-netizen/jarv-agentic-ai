# Render Deployment Guide

Deploy JARV to Render with managed PostgreSQL and Redis. Good for quick deployment with automatic SSL and simple management.

## Cost Estimate

- **Web Services** (Backend, Dashboard): $7/month each = $14/month
- **Background Worker**: $7/month
- **PostgreSQL**: $7/month (1GB storage)
- **Redis**: $10/month
- **Total**: ~$38/month

Or use free tier for testing (services sleep after inactivity).

## Prerequisites

1. Render account (render.com)
2. GitHub repository with JARV code
3. Domain name (optional, Render provides subdomains)

## Step 1: Create PostgreSQL Database

1. Go to Render Dashboard
2. Click **New +** > **PostgreSQL**
3. Settings:
   - Name: `jarv-postgres`
   - Database: `jarv_production`
   - User: `jarv_prod`
   - Region: Select closest to you
   - Plan: **Starter** ($7/month) or **Free** (90 days)
4. Click **Create Database**
5. **Save the Internal Database URL** (starts with `postgres://`)

## Step 2: Create Redis Instance

1. Click **New +** > **Redis**
2. Settings:
   - Name: `jarv-redis`
   - Region: Same as PostgreSQL
   - Plan: **Starter** ($10/month)
   - Eviction Policy: `allkeys-lru`
   - Max Memory: 256MB
3. Click **Create Redis**
4. **Save the Internal Redis URL**

## Step 3: Deploy Backend Service

1. Click **New +** > **Web Service**
2. Connect your GitHub repository
3. Settings:
   - Name: `jarv-backend`
   - Environment: **Docker**
   - Region: Same as database
   - Branch: `main`
   - Dockerfile Path: `apps/backend/Dockerfile`
   - Plan: **Starter** ($7/month)
4. Environment Variables:
   ```
   DATABASE_URL=<Your PostgreSQL Internal URL>
   REDIS_URL=<Your Redis Internal URL>
   SECRET_KEY=<Generate strong key>
   CLAUDE_API_KEY=<Your Claude API key>
   OPENAI_API_KEY=<Your OpenAI API key>
   GEMINI_API_KEY=<Your Gemini API key>
   ENVIRONMENT=production
   LOG_LEVEL=INFO
   CORS_ORIGINS=https://jarv-dashboard.onrender.com
   ```
5. Click **Create Web Service**
6. **Save the Service URL** (e.g., `https://jarv-backend.onrender.com`)

## Step 4: Run Database Migrations

After backend deployment completes:

1. Go to backend service **Shell** tab
2. Run:
   ```bash
   alembic upgrade head
   python -m app.scripts.setup_admin
   ```

## Step 5: Deploy Dashboard

1. Click **New +** > **Web Service**
2. Connect same GitHub repository
3. Settings:
   - Name: `jarv-dashboard`
   - Environment: **Docker**
   - Region: Same as backend
   - Branch: `main`
   - Dockerfile Path: `apps/dashboard/Dockerfile`
   - Plan: **Starter** ($7/month)
4. Environment Variables:
   ```
   NEXT_PUBLIC_API_URL=https://jarv-backend.onrender.com
   NODE_ENV=production
   ```
5. Click **Create Web Service**

## Step 6: Deploy Celery Worker

1. Click **New +** > **Background Worker**
2. Connect same GitHub repository
3. Settings:
   - Name: `jarv-worker`
   - Environment: **Docker**
   - Region: Same as backend
   - Branch: `main`
   - Dockerfile Path: `apps/backend/Dockerfile`
   - Plan: **Starter** ($7/month)
   - Start Command: `celery -A app.workers.celery_app worker --loglevel=info --concurrency=2`
4. Environment Variables: Same as backend
5. Click **Create Background Worker**

## Step 7: Deploy Celery Beat Scheduler

1. Click **New +** > **Background Worker**
2. Connect same GitHub repository
3. Settings:
   - Name: `jarv-scheduler`
   - Environment: **Docker**
   - Region: Same as backend
   - Branch: `main`
   - Dockerfile Path: `apps/backend/Dockerfile`
   - Plan: **Starter** ($7/month)
   - Start Command: `celery -A app.workers.celery_app beat --loglevel=info`
4. Environment Variables: Same as backend
5. Click **Create Background Worker**

## Step 8: Custom Domain (Optional)

1. Go to Dashboard settings
2. Click **Custom Domain**
3. Add your domain: `jarv.yourdomain.com`
4. Follow DNS instructions to add CNAME record
5. SSL certificate is automatically provisioned

Update environment variables:
- Backend `CORS_ORIGINS`: Add your custom domain
- Dashboard `NEXT_PUBLIC_API_URL`: Update if using custom domain for API

## Step 9: Access JARV

Your JARV instance is now running:
- Dashboard: `https://jarv-dashboard.onrender.com` (or your custom domain)
- API: `https://jarv-backend.onrender.com` (or your custom domain)

## Auto-Deploy on Git Push

Render automatically redeploys when you push to your main branch:

```bash
git add .
git commit -m "Update JARV"
git push origin main
```

All services will automatically update.

## Monitoring

1. **Logs**: View in each service's "Logs" tab
2. **Metrics**: Check CPU/Memory in "Metrics" tab
3. **Alerts**: Set up in "Settings" > "Notifications"

## Backup Database

### Manual Backup

```bash
# From Render dashboard, go to PostgreSQL database
# Click "Backups" tab
# Click "Backup Now"
```

### Scheduled Backups

Render automatically backs up databases daily (retained for 7 days on Starter plan).

## Scaling

### Horizontal Scaling

1. Go to service settings
2. Increase **Instance Count**
3. Render handles load balancing automatically

### Vertical Scaling

1. Change service **Plan** to higher tier
2. More CPU/RAM available

## Troubleshooting

### Service Won't Start

Check logs in service dashboard:
```
Settings > Logs > View Logs
```

### Out of Memory

Upgrade service plan or optimize resource usage:
```
Settings > Upgrade Plan
```

### Database Connection Issues

Verify `DATABASE_URL` in environment variables matches your PostgreSQL internal URL.

## Cost Optimization

### Free Tier (Testing)

Use free tier for testing:
- Web Services: Free (sleeps after 15 min inactivity)
- PostgreSQL: Free (90 day trial, then $7/month)
- Redis: Not available on free tier

### Production (Minimal)

- Backend + Dashboard: $14/month
- Worker: $7/month (or combine with backend if low load)
- PostgreSQL: $7/month
- Redis: $10/month
- **Total**: $38/month

For lower costs, consider Oracle Cloud Always Free ($0/month).
