# JARV Agentic AI System - Production Runbook

**Version**: 1.0.0
**Last Updated**: 2026-06-03
**Status**: Production Ready

---

## Table of Contents

1. [Quick Reference](#quick-reference)
2. [Deployment](#deployment)
3. [Daily Operations](#daily-operations)
4. [Monitoring](#monitoring)
5. [Backup and Recovery](#backup-and-recovery)
6. [Troubleshooting](#troubleshooting)
7. [Incident Response](#incident-response)
8. [Maintenance](#maintenance)
9. [Common Tasks](#common-tasks)

---

## Quick Reference

### Service URLs (Production)

```
Dashboard:    https://your-domain.com
API Docs:     https://your-domain.com/api/docs
Health Check: https://your-domain.com/health
Grafana:      http://your-domain.com:3000
Prometheus:   http://your-domain.com:9090
```

### Key Directories

```
Application:  /opt/jarv (or ~/jarv)
Logs:         /opt/jarv/logs
Backups:      /opt/jarv/backups
Config:       /opt/jarv/.env.production
Scripts:      /opt/jarv/scripts
```

### Quick Commands

```bash
# Check service status
docker compose ps

# View logs (all services)
docker compose logs --tail=100 -f

# View logs (specific service)
docker compose logs backend --tail=100 -f

# Restart service
docker compose restart backend

# Restart all services
docker compose restart

# Stop all services
docker compose down

# Start all services
docker compose up -d

# Run backup
bash scripts/backup.sh

# Run tests
docker compose exec backend pytest -m smoke
```

---

## Deployment

### Initial Deployment (Oracle Cloud Always Free)

#### 1. Create VM Instance

```bash
# In Oracle Cloud Console:
# - Compute > Instances > Create Instance
# - Shape: VM.Standard.A1.Flex (ARM) - 4 OCPU, 24 GB RAM
# - Image: Ubuntu 22.04 LTS
# - Storage: 200 GB boot volume
# - Public IP: Assign
# - SSH key: Upload your public key

# Note the public IP address: X.X.X.X
```

#### 2. Connect and Setup

```bash
# SSH to instance
ssh ubuntu@X.X.X.X

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Install git
sudo apt install git -y

# Logout and login again for Docker group to take effect
exit
ssh ubuntu@X.X.X.X
```

#### 3. Configure Firewall

```bash
# In Oracle Cloud Console:
# - Networking > Virtual Cloud Networks > Your VCN > Security Lists
# - Add Ingress Rules:
#   - Port 80 (HTTP)
#   - Port 443 (HTTPS)
#   - Port 22 (SSH) - restricted to your IP

# On the VM:
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

#### 4. Clone and Configure

```bash
# Clone repository
cd /opt
sudo git clone https://github.com/yourusername/jarv.git
sudo chown -R ubuntu:ubuntu jarv
cd jarv

# Create production environment file
cp .env.production.example .env.production

# Edit with your secrets
nano .env.production

# Required variables:
# - SECRET_KEY (generate: openssl rand -hex 32)
# - DATABASE_URL
# - POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
# - REDIS_PASSWORD (generate: openssl rand -hex 16)
# - CLAUDE_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
# - CORS_ORIGINS=https://your-domain.com
```

#### 5. SSL Certificate Setup

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Generate certificate (replace your-domain.com)
sudo certbot certonly --standalone -d your-domain.com

# Certificates will be in:
# /etc/letsencrypt/live/your-domain.com/fullchain.pem
# /etc/letsencrypt/live/your-domain.com/privkey.pem

# Update nginx config to use these certificates
sudo nano infra/nginx/conf.d/jarv.conf

# Set up auto-renewal
sudo certbot renew --dry-run
```

#### 6. Build and Start Services

```bash
# Build images
docker compose -f docker-compose.prod.yml build

# Start services
docker compose -f docker-compose.prod.yml up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

#### 7. Initialize Database

```bash
# Run migrations
docker compose exec backend alembic upgrade head

# Create initial data (optional)
docker compose exec backend python -c "from app.db.init_db import init_db; init_db()"
```

#### 8. Verify Deployment

```bash
# Check health endpoint
curl https://your-domain.com/health

# Should return:
# {"status":"healthy","database":"connected","redis":"connected"}

# Check dashboard
curl https://your-domain.com

# Run smoke tests
docker compose exec backend pytest -m smoke

# Check all services
docker compose ps
```

### Alternative Deployments

#### Render Deployment

See: `infra/render/README.md`

#### Railway Deployment

See: `infra/railway/README.md`

---

## Daily Operations

### Morning Checklist (5 minutes)

```bash
# 1. Check service status
docker compose ps
# All services should be "Up" and healthy

# 2. Check logs for errors
docker compose logs --since 24h | grep -i error

# 3. Check disk usage
df -h
# Ensure / is < 80%

# 4. Check backup status
ls -lh backups/ | tail -5
# Should have daily backups

# 5. Check Grafana dashboards
# Open http://your-domain.com:3000
# Review: API errors, response times, resource usage
```

### Evening Checklist (3 minutes)

```bash
# 1. Check backup completed
ls -lh backups/ | tail -1

# 2. Review error count
docker compose logs --since 24h | grep -i error | wc -l

# 3. Check resource usage
docker stats --no-stream

# 4. Verify health
curl https://your-domain.com/health
```

---

## Monitoring

### Grafana Dashboards

**Access**: http://your-domain.com:3000
**Default Login**: admin / admin (change on first login)

**Key Dashboards**:
1. **System Overview**: CPU, memory, disk, network
2. **API Performance**: Request rate, response time, error rate
3. **Database**: Connections, query time, cache hit rate
4. **Celery**: Queue length, task success rate, worker status
5. **Redis**: Operations, memory usage, hit rate

### Key Metrics to Watch

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| CPU Usage | < 70% | 70-85% | > 85% |
| Memory Usage | < 80% | 80-90% | > 90% |
| Disk Usage | < 70% | 70-85% | > 85% |
| API Error Rate | < 1% | 1-5% | > 5% |
| Response Time (p95) | < 500ms | 500-2000ms | > 2000ms |
| Database Connections | < 15 | 15-18 | > 18 |
| Celery Queue Length | < 50 | 50-100 | > 100 |

### Alerts

**Alert Channels**: (Configure in Grafana)
- Email
- Slack (optional)
- PagerDuty (optional)

**Critical Alerts**:
- Service down (backend, database, redis)
- Disk usage > 90%
- Memory usage > 90%
- Error rate > 5%
- Database connection pool exhausted

**Warning Alerts**:
- CPU usage > 80%
- Memory usage > 85%
- Disk usage > 80%
- Slow response times (p95 > 2s)
- Celery queue backlog > 100

### Log Locations

```bash
# Docker logs
docker compose logs [service]

# Application logs
/opt/jarv/logs/backend.log
/opt/jarv/logs/celery.log

# Nginx logs
/var/log/nginx/access.log
/var/log/nginx/error.log

# System logs
sudo journalctl -u docker
```

---

## Backup and Recovery

### Automated Backup

#### Set Up Cron Job

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * cd /opt/jarv && bash scripts/backup.sh full >> logs/backup.log 2>&1

# Add weekly cleanup (keep 30 days)
0 3 * * 0 find /opt/jarv/backups -name "*.tar.gz" -mtime +30 -delete
```

#### Manual Backup

```bash
# Full backup (database + Redis + files)
cd /opt/jarv
bash scripts/backup.sh full

# Database only
bash scripts/backup.sh database

# Files only
bash scripts/backup.sh files

# Backups saved to: ./backups/jarv-backup-YYYYMMDD-HHMMSS.tar.gz
```

#### Cloud Backup (Optional)

```bash
# Upload to S3 (requires AWS CLI configured)
aws s3 cp backups/jarv-backup-*.tar.gz s3://your-bucket/jarv-backups/

# Upload to GCS (requires gcloud configured)
gsutil cp backups/jarv-backup-*.tar.gz gs://your-bucket/jarv-backups/
```

### Restore Procedure

#### 1. Stop Services

```bash
docker compose down
```

#### 2. Run Restore Script

```bash
# Restore from backup file
bash scripts/restore.sh backups/jarv-backup-YYYYMMDD-HHMMSS.tar.gz

# Or download from cloud first
aws s3 cp s3://your-bucket/jarv-backups/jarv-backup-*.tar.gz ./backups/
bash scripts/restore.sh backups/jarv-backup-*.tar.gz
```

#### 3. Start Services

```bash
docker compose up -d
```

#### 4. Verify Restore

```bash
# Check health
curl https://your-domain.com/health

# Run smoke tests
docker compose exec backend pytest -m smoke

# Check data
docker compose exec backend python -c "from app.db.session import SessionLocal; from app.models import User; print(SessionLocal().query(User).count())"
```

### Disaster Recovery

**Scenario: Complete System Failure**

1. **Provision new VM** (same specs as original)
2. **Install Docker, Docker Compose, Git** (see Initial Deployment)
3. **Clone repository**
4. **Restore from latest backup** (see Restore Procedure)
5. **Update DNS** to point to new VM
6. **Verify all services** working

**Estimated Recovery Time**: 1-2 hours

---

## Troubleshooting

### Service Won't Start

```bash
# Check Docker daemon
sudo systemctl status docker

# Check logs
docker compose logs [service]

# Check resources
docker stats
df -h

# Common fixes:
# - Restart Docker: sudo systemctl restart docker
# - Free disk space: docker system prune -a
# - Check .env.production file has all required variables
```

### Database Connection Errors

```bash
# Check PostgreSQL is running
docker compose ps postgres

# Check PostgreSQL logs
docker compose logs postgres

# Test connection
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT 1;"

# Common fixes:
# - Check DATABASE_URL in .env.production
# - Restart PostgreSQL: docker compose restart postgres
# - Check connection limits: SELECT count(*) FROM pg_stat_activity;
```

### Redis Connection Errors

```bash
# Check Redis is running
docker compose ps redis

# Check Redis logs
docker compose logs redis

# Test connection
docker compose exec redis redis-cli -a $REDIS_PASSWORD ping

# Common fixes:
# - Check REDIS_PASSWORD in .env.production
# - Restart Redis: docker compose restart redis
# - Check memory usage: docker compose exec redis redis-cli -a $REDIS_PASSWORD info memory
```

### High Memory Usage

```bash
# Check memory usage per container
docker stats --no-stream

# Check system memory
free -h

# Top memory consumers
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}" | sort -k2 -h

# Fixes:
# - Restart high-memory service: docker compose restart [service]
# - Reduce worker count in docker-compose.prod.yml
# - Scale down replicas: docker compose scale backend=1
```

### High CPU Usage

```bash
# Check CPU usage
docker stats --no-stream

# Top CPU consumers
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}" | sort -k2 -h

# Check for runaway processes
docker compose exec backend ps aux

# Fixes:
# - Check for stuck tasks: docker compose logs worker
# - Restart service: docker compose restart backend
# - Check Celery queue: docker compose exec worker celery -A app.worker inspect active
```

### Disk Full

```bash
# Check disk usage
df -h

# Find large files
du -sh /opt/jarv/* | sort -h

# Clean up Docker
docker system prune -a --volumes

# Clean up logs
sudo rm /var/log/nginx/*.log.*.gz
sudo journalctl --vacuum-time=7d

# Clean up old backups
find /opt/jarv/backups -name "*.tar.gz" -mtime +30 -delete
```

### Slow API Responses

```bash
# Check database query performance
docker compose logs backend | grep "slow query"

# Check connection pool
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT count(*) FROM pg_stat_activity;"

# Check Redis latency
docker compose exec redis redis-cli -a $REDIS_PASSWORD --latency

# Check Grafana for bottlenecks
# Open: http://your-domain.com:3000

# Fixes:
# - Add database indices
# - Increase database connection pool
# - Enable query caching
# - Scale backend replicas
```

### Celery Tasks Not Processing

```bash
# Check worker status
docker compose ps worker

# Check worker logs
docker compose logs worker

# Check queue length
docker compose exec worker celery -A app.worker inspect active

# Check scheduled tasks
docker compose exec worker celery -A app.worker inspect scheduled

# Fixes:
# - Restart workers: docker compose restart worker
# - Check Redis connection
# - Purge queue if needed: docker compose exec worker celery -A app.worker purge
```

### SSL Certificate Issues

```bash
# Check certificate validity
sudo certbot certificates

# Test renewal
sudo certbot renew --dry-run

# Renew certificate
sudo certbot renew

# Reload Nginx
docker compose restart nginx

# Common fixes:
# - Check domain DNS points to server
# - Ensure ports 80 and 443 are open
# - Check certificate paths in nginx config
```

---

## Incident Response

### Severity Levels

**P0 - Critical**: Complete service outage
**P1 - High**: Major functionality impaired
**P2 - Medium**: Minor functionality impaired
**P3 - Low**: Cosmetic or minor issues

### Response Procedures

#### P0: Complete Outage

1. **Acknowledge** incident (< 5 min)
2. **Check health endpoint**: `curl https://your-domain.com/health`
3. **Check service status**: `docker compose ps`
4. **Check logs**: `docker compose logs --tail=100`
5. **Restart services**: `docker compose restart`
6. **If database issue**: Restore from latest backup
7. **Monitor recovery**: Check Grafana dashboards
8. **Document incident**: What happened, what fixed it
9. **Post-mortem**: Within 48 hours

#### P1: Major Functionality Impaired

1. **Acknowledge** incident (< 15 min)
2. **Identify affected service**: Check logs and monitoring
3. **Restart affected service**: `docker compose restart [service]`
4. **Check for recent changes**: `git log --oneline -10`
5. **Roll back if needed**: `git checkout previous-commit && docker compose up -d`
6. **Monitor recovery**
7. **Document incident**

#### P2: Minor Functionality Impaired

1. **Log incident** for investigation
2. **Create ticket** if needed
3. **Monitor for escalation**
4. **Fix in next maintenance window**

### Rollback Procedure

```bash
# Stop services
docker compose down

# Check out previous version
git log --oneline -10  # Find previous commit
git checkout <previous-commit>

# Rebuild images
docker compose -f docker-compose.prod.yml build

# Start services
docker compose up -d

# Verify
curl https://your-domain.com/health
docker compose exec backend pytest -m smoke
```

### Emergency Contacts

```
Primary Contact: [Your Name/Team]
Email: [your-email]
Phone: [your-phone]
Escalation: [manager/on-call]

External Services:
- Domain Registrar: [registrar support]
- Oracle Cloud: support.oracle.com
- LLM Providers: Claude, OpenAI, Gemini support
```

---

## Maintenance

### Weekly Maintenance (30 minutes)

```bash
# 1. Update dependencies (test in staging first)
docker compose exec backend pip list --outdated

# 2. Check Docker image updates
docker compose pull

# 3. Clean up Docker resources
docker system prune -f

# 4. Review error logs
docker compose logs --since 7d | grep -i error | less

# 5. Check disk usage trends
df -h

# 6. Review Grafana dashboards
# Check for unusual patterns or trends

# 7. Test backup restore (monthly)
bash scripts/restore.sh backups/latest-backup.tar.gz
```

### Monthly Maintenance (1-2 hours)

```bash
# 1. Security updates
sudo apt update && sudo apt upgrade -y

# 2. Update Docker
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 3. Rotate secrets (quarterly)
# Update .env.production with new secrets
docker compose down
docker compose up -d

# 4. Review and update firewall rules
sudo ufw status

# 5. Test disaster recovery
# Perform full restore on test instance

# 6. Review monitoring alerts
# Tune thresholds if needed

# 7. Update documentation
# Document any changes or procedures

# 8. Security scan
docker compose exec backend pip-audit
```

### Quarterly Maintenance (2-4 hours)

```bash
# 1. Full system backup verification
# Restore backup to separate instance and verify

# 2. Load testing
# Use k6 or Apache Bench to test performance

# 3. Security audit
# Review infra/security/README.md checklist

# 4. Dependency updates
# Update Python packages, npm packages
# Test thoroughly before deploying

# 5. Database maintenance
# Vacuum, analyze, reindex
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "VACUUM ANALYZE;"

# 6. Review and optimize queries
# Check slow query log, add indices if needed

# 7. Capacity planning
# Review trends, plan for scaling

# 8. Documentation review
# Update runbook with lessons learned
```

---

## Common Tasks

### Add New User

```bash
docker compose exec backend python -c "
from app.db.session import SessionLocal
from app.models import User
from app.core.security import get_password_hash

db = SessionLocal()
user = User(
    email='user@example.com',
    hashed_password=get_password_hash('secure-password'),
    is_active=True
)
db.add(user)
db.commit()
print(f'Created user: {user.email}')
"
```

### Run Database Migration

```bash
# Create new migration
docker compose exec backend alembic revision --autogenerate -m "description"

# Review migration
cat apps/backend/alembic/versions/latest_migration.py

# Apply migration
docker compose exec backend alembic upgrade head

# Rollback one migration
docker compose exec backend alembic downgrade -1
```

### Scale Services

```bash
# Scale backend to 4 replicas
docker compose up -d --scale backend=4

# Scale workers to 3
docker compose up -d --scale worker=3

# Check scaling
docker compose ps
```

### Update Environment Variables

```bash
# 1. Edit .env.production
nano .env.production

# 2. Restart affected services
docker compose down
docker compose up -d

# 3. Verify changes
docker compose exec backend env | grep YOUR_VAR
```

### View Real-Time Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs backend -f

# Last 100 lines
docker compose logs backend --tail=100 -f

# Filter by keyword
docker compose logs -f | grep -i error
```

### Execute Commands in Container

```bash
# Open shell in backend
docker compose exec backend bash

# Run Python script
docker compose exec backend python scripts/your-script.py

# Run pytest
docker compose exec backend pytest

# Open PostgreSQL shell
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB

# Open Redis shell
docker compose exec redis redis-cli -a $REDIS_PASSWORD
```

### Check Service Health

```bash
# All services
curl https://your-domain.com/health

# Database
docker compose exec postgres pg_isready -U $POSTGRES_USER

# Redis
docker compose exec redis redis-cli -a $REDIS_PASSWORD ping

# Backend
curl https://your-domain.com/api/health

# Dashboard
curl https://your-domain.com
```

### Cleanup Old Data

```bash
# Delete old logs (> 30 days)
docker compose exec backend python -c "
from app.db.session import SessionLocal
from app.models import Log
from datetime import datetime, timedelta

db = SessionLocal()
cutoff = datetime.now() - timedelta(days=30)
deleted = db.query(Log).filter(Log.created_at < cutoff).delete()
db.commit()
print(f'Deleted {deleted} old log entries')
"

# Vacuum database
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "VACUUM ANALYZE;"
```

---

## Quick Troubleshooting Decision Tree

```
Service Issue?
├─ Service won't start
│  ├─ Check Docker: systemctl status docker
│  ├─ Check logs: docker compose logs [service]
│  └─ Check resources: df -h, free -h
│
├─ Service slow
│  ├─ Check CPU: docker stats
│  ├─ Check logs for errors
│  └─ Check Grafana dashboards
│
├─ Database errors
│  ├─ Check connection: docker compose ps postgres
│  ├─ Check pool: SELECT count(*) FROM pg_stat_activity
│  └─ Restart if needed: docker compose restart postgres
│
└─ Can't connect
   ├─ Check firewall: sudo ufw status
   ├─ Check Nginx: docker compose logs nginx
   └─ Check SSL: sudo certbot certificates
```

---

## Emergency Commands

```bash
# Stop everything immediately
docker compose down

# Restart everything
docker compose restart

# View all container status
docker compose ps

# Check all logs for errors
docker compose logs | grep -i error

# Restore from backup
bash scripts/restore.sh backups/latest-backup.tar.gz

# Rebuild and restart (use after code changes)
docker compose down
docker compose build
docker compose up -d
```

---

## Appendix

### Useful Docker Commands

```bash
# Remove all stopped containers
docker container prune

# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune

# Show disk usage
docker system df

# Clean everything (use with caution!)
docker system prune -a --volumes
```

### Useful PostgreSQL Commands

```bash
# List databases
docker compose exec postgres psql -U $POSTGRES_USER -l

# List tables
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt"

# Show table schema
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\d table_name"

# Count rows
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT COUNT(*) FROM users;"

# Database size
docker compose exec postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "SELECT pg_size_pretty(pg_database_size('$POSTGRES_DB'));"
```

### Useful Redis Commands

```bash
# Get info
docker compose exec redis redis-cli -a $REDIS_PASSWORD info

# List keys
docker compose exec redis redis-cli -a $REDIS_PASSWORD keys "*"

# Get memory usage
docker compose exec redis redis-cli -a $REDIS_PASSWORD info memory

# Flush all (use with caution!)
docker compose exec redis redis-cli -a $REDIS_PASSWORD flushall
```

---

**End of Runbook**

For additional documentation, see:
- BUILD_LEDGER.md (development history)
- FINAL_PRODUCTION_READINESS_REPORT.md (deployment assessment)
- infra/*/README.md (infrastructure guides)
