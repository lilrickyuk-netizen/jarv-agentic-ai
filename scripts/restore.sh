#!/bin/bash
#
# JARV Restore Script
# Restores PostgreSQL database and application data from backup
#
# Usage: ./scripts/restore.sh <backup-name>
# Example: ./scripts/restore.sh jarv_full_20240101_120000
#

set -e

# Configuration
BACKUP_NAME="$1"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
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
    if [ -z "$BACKUP_NAME" ]; then
        log_error "Backup name not specified"
        echo "Usage: $0 <backup-name>"
        echo ""
        echo "Available backups:"
        ls -1 "$BACKUP_DIR" | grep "jarv_.*\.tar\.gz" || echo "  No backups found"
        exit 1
    fi

    if [ ! -f "$BACKUP_DIR/${BACKUP_NAME}.tar.gz" ]; then
        log_error "Backup not found: $BACKUP_DIR/${BACKUP_NAME}.tar.gz"
        exit 1
    fi

    log_info "Prerequisites check passed"
}

confirm_restore() {
    log_warn "WARNING: This will overwrite the current database and data!"
    log_warn "Backup to restore: $BACKUP_NAME"
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " confirmation

    if [ "$confirmation" != "yes" ]; then
        log_info "Restore cancelled by user"
        exit 0
    fi
}

extract_backup() {
    log_info "Extracting backup..."

    cd "$BACKUP_DIR"
    tar -xzf "${BACKUP_NAME}.tar.gz"

    if [ ! -d "$BACKUP_NAME" ]; then
        log_error "Failed to extract backup"
        exit 1
    fi

    cd - > /dev/null
    log_info "Backup extracted successfully"
}

restore_database() {
    if [ ! -f "$BACKUP_DIR/$BACKUP_NAME/database.dump" ]; then
        log_warn "No database backup found in this archive"
        return
    fi

    log_info "Restoring PostgreSQL database..."

    # Stop services that use the database
    log_info "Stopping services..."
    docker compose -f "$COMPOSE_FILE" stop backend worker scheduler cloud-runner

    # Drop existing connections
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
        -U "${POSTGRES_USER:-jarv_prod}" \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB:-jarv_production}' AND pid <> pg_backend_pid();" \
        || true

    # Drop and recreate database
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
        -U "${POSTGRES_USER:-jarv_prod}" \
        -c "DROP DATABASE IF EXISTS ${POSTGRES_DB:-jarv_production};" \
        postgres

    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
        -U "${POSTGRES_USER:-jarv_prod}" \
        -c "CREATE DATABASE ${POSTGRES_DB:-jarv_production};" \
        postgres

    # Restore database
    cat "$BACKUP_DIR/$BACKUP_NAME/database.dump" | \
        docker compose -f "$COMPOSE_FILE" exec -T postgres pg_restore \
        -U "${POSTGRES_USER:-jarv_prod}" \
        -d "${POSTGRES_DB:-jarv_production}" \
        --no-owner --no-acl

    if [ $? -eq 0 ]; then
        log_info "Database restored successfully"
    else
        log_error "Database restore failed"
        exit 1
    fi

    # Restart services
    log_info "Restarting services..."
    docker compose -f "$COMPOSE_FILE" up -d backend worker scheduler cloud-runner
}

restore_redis() {
    if [ ! -f "$BACKUP_DIR/$BACKUP_NAME/redis.rdb" ]; then
        log_warn "No Redis backup found in this archive"
        return
    fi

    log_info "Restoring Redis data..."

    docker compose -f "$COMPOSE_FILE" stop redis

    docker compose -f "$COMPOSE_FILE" cp \
        "$BACKUP_DIR/$BACKUP_NAME/redis.rdb" \
        redis:/data/dump.rdb

    docker compose -f "$COMPOSE_FILE" start redis

    log_info "Redis data restored successfully"
}

restore_application_data() {
    if [ -f "$BACKUP_DIR/$BACKUP_NAME/assets.tar.gz" ]; then
        log_info "Restoring assets..."
        tar -xzf "$BACKUP_DIR/$BACKUP_NAME/assets.tar.gz" -C .
        log_info "Assets restored"
    fi

    if [ -f "$BACKUP_DIR/$BACKUP_NAME/logs.tar.gz" ]; then
        log_info "Restoring logs..."
        tar -xzf "$BACKUP_DIR/$BACKUP_NAME/logs.tar.gz" -C .
        log_info "Logs restored"
    fi
}

verify_restore() {
    log_info "Verifying restore..."

    # Wait for services to be ready
    sleep 10

    # Check backend health
    if docker compose -f "$COMPOSE_FILE" exec -T backend curl -f http://localhost:8000/health > /dev/null 2>&1; then
        log_info "Backend health check passed"
    else
        log_warn "Backend health check failed - services may still be starting"
    fi

    # Check database connection
    if docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U "${POSTGRES_USER:-jarv_prod}" -d "${POSTGRES_DB:-jarv_production}" -c "SELECT 1;" > /dev/null 2>&1; then
        log_info "Database connection verified"
    else
        log_error "Database connection failed"
        exit 1
    fi
}

cleanup() {
    log_info "Cleaning up temporary files..."
    rm -rf "$BACKUP_DIR/$BACKUP_NAME"
    log_info "Cleanup complete"
}

# Main execution
main() {
    log_info "Starting JARV restore process..."

    check_prerequisites
    confirm_restore
    extract_backup
    restore_database
    restore_redis
    restore_application_data
    verify_restore
    cleanup

    log_info "Restore completed successfully!"
    log_info "Please verify that all services are running correctly."
}

# Error handling
trap 'log_error "Restore failed at line $LINENO"; cleanup; exit 1' ERR

# Run main
main
