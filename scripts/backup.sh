#!/bin/bash
#
# JARV Backup Script
# Backs up PostgreSQL database and application data
#
# Usage: ./scripts/backup.sh [backup-type]
# backup-type: full (default), database-only, files-only
#

set -e

# Configuration
BACKUP_TYPE="${1:-full}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="jarv_${BACKUP_TYPE}_${BACKUP_TIMESTAMP}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

# Docker compose file
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi

    if ! docker compose -f "$COMPOSE_FILE" ps &> /dev/null; then
        log_error "Docker Compose services not found"
        exit 1
    fi

    log_info "Prerequisites check passed"
}

create_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    mkdir -p "$BACKUP_DIR/$BACKUP_NAME"
    log_info "Created backup directory: $BACKUP_DIR/$BACKUP_NAME"
}

backup_database() {
    log_info "Backing up PostgreSQL database..."

    docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump \
        -U "${POSTGRES_USER:-jarv_prod}" \
        -d "${POSTGRES_DB:-jarv_production}" \
        --format=custom \
        --compress=9 \
        > "$BACKUP_DIR/$BACKUP_NAME/database.dump"

    if [ $? -eq 0 ]; then
        log_info "Database backup completed: database.dump"
    else
        log_error "Database backup failed"
        exit 1
    fi
}

backup_redis() {
    log_info "Backing up Redis data..."

    docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli \
        --rdb /data/dump.rdb SAVE

    docker compose -f "$COMPOSE_FILE" cp \
        redis:/data/dump.rdb \
        "$BACKUP_DIR/$BACKUP_NAME/redis.rdb"

    if [ $? -eq 0 ]; then
        log_info "Redis backup completed: redis.rdb"
    else
        log_warn "Redis backup failed (non-critical)"
    fi
}

backup_application_data() {
    log_info "Backing up application data..."

    # Backup environment files (without secrets)
    if [ -f ".env.production" ]; then
        grep -v -E '(PASSWORD|SECRET|KEY|TOKEN)' .env.production > "$BACKUP_DIR/$BACKUP_NAME/env.template" || true
        log_info "Environment template backed up"
    fi

    # Backup uploaded assets if directory exists
    if [ -d "data/assets" ]; then
        tar -czf "$BACKUP_DIR/$BACKUP_NAME/assets.tar.gz" data/assets
        log_info "Assets backed up: assets.tar.gz"
    fi

    # Backup logs
    if [ -d "logs" ]; then
        tar -czf "$BACKUP_DIR/$BACKUP_NAME/logs.tar.gz" logs
        log_info "Logs backed up: logs.tar.gz"
    fi
}

create_backup_manifest() {
    log_info "Creating backup manifest..."

    cat > "$BACKUP_DIR/$BACKUP_NAME/manifest.txt" <<EOF
JARV Backup Manifest
====================
Backup Type: $BACKUP_TYPE
Backup Date: $(date)
Backup Name: $BACKUP_NAME

Contents:
$(ls -lh "$BACKUP_DIR/$BACKUP_NAME" | tail -n +2)

Database Info:
- Database: ${POSTGRES_DB:-jarv_production}
- User: ${POSTGRES_USER:-jarv_prod}

System Info:
- Hostname: $(hostname)
- Docker Version: $(docker --version)
- Compose Version: $(docker compose version)

To restore this backup, run:
  ./scripts/restore.sh $BACKUP_NAME
EOF

    log_info "Manifest created: manifest.txt"
}

compress_backup() {
    log_info "Compressing backup..."

    cd "$BACKUP_DIR"
    tar -czf "${BACKUP_NAME}.tar.gz" "$BACKUP_NAME"

    if [ $? -eq 0 ]; then
        rm -rf "$BACKUP_NAME"
        log_info "Backup compressed: ${BACKUP_NAME}.tar.gz"
        log_info "Backup size: $(du -h "${BACKUP_NAME}.tar.gz" | cut -f1)"
    else
        log_error "Backup compression failed"
        exit 1
    fi

    cd - > /dev/null
}

cleanup_old_backups() {
    log_info "Cleaning up old backups (retention: $RETENTION_DAYS days)..."

    find "$BACKUP_DIR" -name "jarv_*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete

    local deleted_count=$(find "$BACKUP_DIR" -name "jarv_*.tar.gz" -type f -mtime +$RETENTION_DAYS | wc -l)
    log_info "Deleted $deleted_count old backup(s)"
}

upload_to_cloud() {
    if [ -n "$BACKUP_S3_BUCKET" ] && command -v aws &> /dev/null; then
        log_info "Uploading backup to S3..."

        aws s3 cp "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" \
            "s3://$BACKUP_S3_BUCKET/backups/${BACKUP_NAME}.tar.gz"

        if [ $? -eq 0 ]; then
            log_info "Backup uploaded to S3"
        else
            log_warn "S3 upload failed (non-critical)"
        fi
    fi

    if [ -n "$BACKUP_GCS_BUCKET" ] && command -v gsutil &> /dev/null; then
        log_info "Uploading backup to Google Cloud Storage..."

        gsutil cp "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" \
            "gs://$BACKUP_GCS_BUCKET/backups/${BACKUP_NAME}.tar.gz"

        if [ $? -eq 0 ]; then
            log_info "Backup uploaded to GCS"
        else
            log_warn "GCS upload failed (non-critical)"
        fi
    fi
}

send_notification() {
    local status=$1
    local message=$2

    if [ -n "$BACKUP_WEBHOOK_URL" ]; then
        curl -X POST "$BACKUP_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"status\":\"$status\",\"message\":\"$message\",\"backup\":\"$BACKUP_NAME\"}" \
            &> /dev/null || true
    fi
}

# Main execution
main() {
    log_info "Starting JARV backup process..."
    log_info "Backup type: $BACKUP_TYPE"

    check_prerequisites
    create_backup_dir

    case "$BACKUP_TYPE" in
        full)
            backup_database
            backup_redis
            backup_application_data
            ;;
        database-only)
            backup_database
            backup_redis
            ;;
        files-only)
            backup_application_data
            ;;
        *)
            log_error "Invalid backup type: $BACKUP_TYPE"
            log_error "Valid types: full, database-only, files-only"
            exit 1
            ;;
    esac

    create_backup_manifest
    compress_backup
    cleanup_old_backups
    upload_to_cloud

    log_info "Backup completed successfully!"
    log_info "Backup location: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"

    send_notification "success" "Backup completed successfully"
}

# Error handling
trap 'log_error "Backup failed at line $LINENO"; send_notification "error" "Backup failed"; exit 1' ERR

# Run main
main
