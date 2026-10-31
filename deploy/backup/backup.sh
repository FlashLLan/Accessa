#!/usr/bin/env bash
# Daily PostgreSQL backup for the docker-compose.prod.yml deployment.
#
#   deploy/backup/backup.sh                 # writes $BACKUP_DIR/accessa-<UTC time>.dump
#
# Custom-format pg_dump (includes the GRANT/REVOKE statements, so the restored
# audit_logs stays append-only for accessa_app). Run as the deploy user from cron;
# see DEPLOYMENT.md. Keeps BACKUP_KEEP_DAYS days of dumps.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-.env.production}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/accessa}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_DIR/accessa-$STAMP.dump"

umask 077
mkdir -p "$BACKUP_DIR"
cd "$REPO_DIR"

docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
    pg_dump --username=postgres --dbname=accessa --format=custom --compress=6 > "$TARGET.partial"

# A dump that cannot be listed is not a backup.
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres \
    pg_restore --list < "$TARGET.partial" > /dev/null
mv "$TARGET.partial" "$TARGET"

find "$BACKUP_DIR" -name 'accessa-*.dump' -type f -mtime +"$BACKUP_KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: $TARGET ($(du -h "$TARGET" | cut -f1))"
