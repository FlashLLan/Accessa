#!/usr/bin/env bash
# Restore test: restores a dump into a throwaway PostgreSQL container (never the
# live database) and checks that the data and the audit_logs rights came back.
#
#   deploy/backup/restore-test.sh                       # latest dump in $BACKUP_DIR
#   deploy/backup/restore-test.sh /path/to/accessa.dump
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/accessa}"
# shellcheck disable=SC2012  # file names are written by backup.sh (no odd characters)
DUMP="${1:-$(ls -1t "$BACKUP_DIR"/accessa-*.dump 2>/dev/null | head -n 1)}"
if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "no dump found in $BACKUP_DIR" >&2
    exit 1
fi

NAME="accessa-restore-test-$$"
cleanup() { docker rm -f "$NAME" > /dev/null 2>&1 || true; }
trap cleanup EXIT

# Same image and init script as production, so accessa_owner/accessa_app exist
# for the ownership and GRANTs in the dump. Throwaway passwords, no ports.
docker run -d --name "$NAME" --network none \
    -e POSTGRES_PASSWORD="$(openssl rand -hex 16)" -e POSTGRES_DB=accessa \
    -e ACCESSA_OWNER_PASSWORD="$(openssl rand -hex 16)" -e ACCESSA_APP_PASSWORD="$(openssl rand -hex 16)" \
    -v "$REPO_DIR/docker/postgres/init:/docker-entrypoint-initdb.d:ro" \
    postgres:16 > /dev/null

for _ in $(seq 1 60); do
    [ "$(docker logs "$NAME" 2>&1 | grep -c 'ready to accept connections')" -ge 2 ] && break
    sleep 1
done

docker exec -i "$NAME" pg_restore --username=postgres --dbname=accessa --exit-on-error --single-transaction < "$DUMP"

psql() { docker exec -i "$NAME" psql --username=postgres --dbname=accessa -tA -v ON_ERROR_STOP=1 -c "$1"; }
echo "restored $DUMP"
echo "  alembic revision:   $(psql 'SELECT version_num FROM alembic_version')"
echo "  workspaces / users: $(psql 'SELECT count(*) FROM workspaces') / $(psql 'SELECT count(*) FROM users')"
echo "  change requests:    $(psql 'SELECT count(*) FROM change_requests')"
echo "  audit entries:      $(psql 'SELECT count(*) FROM audit_logs')"
APPEND_ONLY="$(psql "SELECT NOT has_table_privilege('accessa_app','audit_logs','UPDATE')
                      AND NOT has_table_privilege('accessa_app','audit_logs','DELETE')
                      AND has_table_privilege('accessa_app','audit_logs','INSERT')")"
echo "  audit_logs append-only for accessa_app: $APPEND_ONLY"
[ "$APPEND_ONLY" = "t" ] || { echo "RESTORE TEST FAILED: audit_logs rights not restored" >&2; exit 1; }
echo "RESTORE TEST OK"
