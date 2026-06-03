# JARV Backup and Recovery

Comprehensive backup and disaster recovery procedures for JARV production systems.

## Overview

JARV backup system includes:
- **Database backups**: PostgreSQL dumps with compression
- **Redis backups**: RDB snapshots
- **Application data**: Uploaded assets and logs
- **Automated scheduling**: Daily backups with retention policy
- **Cloud storage**: Optional S3/GCS upload
- **Point-in-time recovery**: Timestamp-based restore

## Quick Start

### Manual Backup

```bash
# Full backup (database + Redis + files)
./scripts/backup.sh full

# Database only
./scripts/backup.sh database-only

# Files only
./scripts/backup.sh files-only
```

Backups are stored in `./backups/` directory.

### Manual Restore

```bash
# List available backups
ls -1 backups/*.tar.gz

# Restore from backup
./scripts/restore.sh jarv_full_20240101_120000
```

**WARNING**: Restore will overwrite current database and data!

## Automated Backups

### Option 1: Cron Job (Linux/Oracle Cloud)

Add to crontab:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * cd /home/ubuntu/jarv && ./scripts/backup.sh full >> /var/log/jarv-backup.log 2>&1

# Add weekly full backup on Sunday at 3 AM
0 3 * * 0 cd /home/ubuntu/jarv && BACKUP_DIR=/mnt/backups ./scripts/backup.sh full >> /var/log/jarv-backup.log 2>&1
```

### Option 2: Systemd Timer (Alternative to Cron)

Create `/etc/systemd/system/jarv-backup.service`:

```ini
[Unit]
Description=JARV Backup Service
After=docker.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/jarv
ExecStart=/home/ubuntu/jarv/scripts/backup.sh full
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/jarv-backup.timer`:

```ini
[Unit]
Description=JARV Backup Timer
Requires=jarv-backup.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable jarv-backup.timer
sudo systemctl start jarv-backup.timer

# Check status
sudo systemctl status jarv-backup.timer
sudo systemctl list-timers
```

### Option 3: GitHub Actions (Cloud Backup)

Create `.github/workflows/backup.yml`:

```yaml
name: Scheduled Backup

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM UTC
  workflow_dispatch:

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Run backup on Oracle Cloud
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.ORACLE_VM_HOST }}
          username: ${{ secrets.ORACLE_VM_USER }}
          key: ${{ secrets.ORACLE_VM_SSH_KEY }}
          script: |
            cd ~/jarv
            ./scripts/backup.sh full

      - name: Upload to S3
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: ${{ secrets.ORACLE_VM_HOST }}
          username: ${{ secrets.ORACLE_VM_USER }}
          key: ${{ secrets.ORACLE_VM_SSH_KEY }}
          script: |
            cd ~/jarv/backups
            latest_backup=$(ls -t jarv_*.tar.gz | head -1)
            aws s3 cp "$latest_backup" "s3://${{ secrets.BACKUP_S3_BUCKET }}/backups/"
```

## Cloud Storage Integration

### AWS S3

Install AWS CLI:

```bash
sudo apt-get install awscli -y
aws configure
```

Set environment variables:

```bash
export BACKUP_S3_BUCKET=jarv-backups-production
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-east-1
```

Backup script will automatically upload to S3.

### Google Cloud Storage

Install gsutil:

```bash
curl https://sdk.cloud.google.com | bash
gcloud auth login
```

Set environment variables:

```bash
export BACKUP_GCS_BUCKET=jarv-backups-production
```

Backup script will automatically upload to GCS.

## Backup Configuration

### Environment Variables

Create `.backup.env`:

```bash
# Backup settings
BACKUP_DIR=./backups
RETENTION_DAYS=30
COMPOSE_FILE=docker-compose.prod.yml

# Cloud storage (optional)
BACKUP_S3_BUCKET=jarv-backups-production
BACKUP_GCS_BUCKET=jarv-backups-production

# Notifications (optional)
BACKUP_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Database credentials (auto-detected from .env.production)
POSTGRES_USER=jarv_prod
POSTGRES_PASSWORD=your-password
POSTGRES_DB=jarv_production
```

Load before running backup:

```bash
source .backup.env
./scripts/backup.sh full
```

## Backup Strategies

### 3-2-1 Backup Rule

For production, follow the 3-2-1 rule:
- **3** copies of data (original + 2 backups)
- **2** different storage types (local + cloud)
- **1** off-site backup (cloud storage)

### Recommended Strategy

**Daily backups**:
- Keep on local disk: 7 days
- Upload to cloud: 30 days retention

**Weekly backups**:
- Keep on local disk: 4 weeks
- Upload to cloud: 12 months retention

**Monthly backups**:
- Upload to cloud: 3 years retention

### Implementation

```bash
# Daily backup (2 AM)
0 2 * * * cd /home/ubuntu/jarv && ./scripts/backup.sh full

# Weekly full backup (Sunday 3 AM)
0 3 * * 0 cd /home/ubuntu/jarv && RETENTION_DAYS=120 ./scripts/backup.sh full

# Monthly backup (1st of month, 4 AM)
0 4 1 * * cd /home/ubuntu/jarv && RETENTION_DAYS=1095 ./scripts/backup.sh full
```

## Disaster Recovery

### Scenario 1: Database Corruption

```bash
# Stop services
docker compose -f docker-compose.prod.yml down

# Restore from latest backup
./scripts/restore.sh jarv_full_YYYYMMDD_HHMMSS

# Verify services
docker compose -f docker-compose.prod.yml logs -f backend
```

### Scenario 2: Complete Server Loss

On new server:

```bash
# Clone repository
git clone https://github.com/yourusername/jarv.git
cd jarv

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Download backup from cloud
aws s3 cp s3://jarv-backups-production/backups/jarv_full_YYYYMMDD_HHMMSS.tar.gz ./backups/

# Extract and restore
cd backups
tar -xzf jarv_full_YYYYMMDD_HHMMSS.tar.gz
cd ..
./scripts/restore.sh jarv_full_YYYYMMDD_HHMMSS

# Configure and start
cp .env.production.example .env.production
# Edit .env.production with credentials
docker compose -f docker-compose.prod.yml up -d
```

### Scenario 3: Point-in-Time Recovery

If you need to restore to a specific point in time:

```bash
# Find backup closest to desired time
ls -lt backups/*.tar.gz

# Restore that backup
./scripts/restore.sh jarv_full_YYYYMMDD_HHMMSS

# If using WAL archiving (PostgreSQL), restore transaction logs
# (Advanced - requires WAL archiving to be configured)
```

## Backup Verification

### Test Restores

Regularly test backup restores:

```bash
# Monthly restore test
./scripts/test-restore.sh

# Or manually:
# 1. Restore to test environment
# 2. Verify data integrity
# 3. Check application functionality
# 4. Document results
```

### Backup Integrity Check

Verify backup file integrity:

```bash
# Check backup archive
tar -tzf backups/jarv_full_YYYYMMDD_HHMMSS.tar.gz

# Check database dump
pg_restore --list backups/jarv_full_YYYYMMDD_HHMMSS/database.dump
```

## Monitoring Backups

### Check Last Backup

```bash
# List recent backups
ls -lth backups/*.tar.gz | head -5

# Check backup age
last_backup=$(ls -t backups/*.tar.gz | head -1)
backup_age=$(($(date +%s) - $(stat -c %Y "$last_backup")))
echo "Last backup is $((backup_age / 3600)) hours old"
```

### Alert on Backup Failure

Add to backup script or cron:

```bash
#!/bin/bash
./scripts/backup.sh full

if [ $? -ne 0 ]; then
    # Send alert
    curl -X POST "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" \
        -H "Content-Type: application/json" \
        -d '{"text":"JARV backup failed!"}'
fi
```

### Backup Monitoring Service

Use UptimeRobot or similar to check backup freshness:

1. Create script that checks last backup age
2. Expose as HTTP endpoint
3. Monitor endpoint with UptimeRobot

## Backup Security

### Encrypt Backups

For sensitive data, encrypt backups:

```bash
# Encrypt backup
gpg --encrypt --recipient your-email@example.com backups/jarv_full_*.tar.gz

# Upload encrypted version
aws s3 cp backups/jarv_full_*.tar.gz.gpg s3://your-bucket/

# Decrypt for restore
gpg --decrypt backups/jarv_full_*.tar.gz.gpg > backups/jarv_full_*.tar.gz
```

### Secure Cloud Storage

- Use IAM roles with minimum permissions
- Enable bucket versioning
- Enable server-side encryption
- Set up bucket policies to prevent deletion
- Use MFA delete for critical backups

## Backup Costs

### Oracle Cloud (Free Tier)

- Local storage: 200 GB free
- Block storage: Free
- **Cost: $0/month**

### AWS S3

- Standard storage: $0.023/GB/month
- 100 GB backups: ~$2.30/month
- With Glacier for archives: ~$0.40/month

### Google Cloud Storage

- Standard storage: $0.020/GB/month
- 100 GB backups: ~$2/month
- With Archive tier: ~$0.12/month

### Backblaze B2

- Storage: $0.005/GB/month
- 100 GB backups: ~$0.50/month
- First 10 GB free

## Best Practices

1. **Automate backups**: Never rely on manual backups
2. **Test restores regularly**: Backup is only good if restore works
3. **Monitor backup status**: Alert on failures
4. **Use multiple locations**: Don't rely on single storage
5. **Document procedures**: Keep recovery playbook updated
6. **Encrypt sensitive data**: Protect backup contents
7. **Version control configs**: Track infrastructure changes
8. **Set retention policies**: Don't keep backups forever
9. **Audit backup access**: Track who can access backups
10. **Practice disaster recovery**: Run DR drills quarterly

## Troubleshooting

### Backup Fails

```bash
# Check disk space
df -h

# Check Docker services
docker compose -f docker-compose.prod.yml ps

# Check PostgreSQL
docker compose -f docker-compose.prod.yml exec postgres pg_isready

# View backup logs
tail -f /var/log/jarv-backup.log
```

### Restore Fails

```bash
# Check backup integrity
tar -tzf backups/jarv_full_*.tar.gz

# Verify database dump
pg_restore --list backups/jarv_full_*/database.dump

# Check PostgreSQL logs
docker compose -f docker-compose.prod.yml logs postgres

# Try manual restore
cat backups/jarv_full_*/database.dump | \
    docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_restore -U jarv_prod -d jarv_production --verbose
```

### Out of Disk Space

```bash
# Remove old backups manually
find backups -name "jarv_*.tar.gz" -mtime +30 -delete

# Clean Docker volumes
docker system prune -a

# Compress older backups with higher compression
gzip -9 backups/old-backup.tar
```
