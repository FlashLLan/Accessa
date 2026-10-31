#!/usr/bin/env bash
# Update the docker-compose.prod.yml deployment to a branch or tag.
#
#   deploy/update.sh                  # the thesis branch
#   deploy/update.sh v1.2.0           # a tag (or any other branch)
#
# Run on the server as the deploy user, from the repository directory. Steps:
# backup, fetch and check out (fast-forward only), build, migrations as the schema
# owner in a one-off container, restart, health check, prune old images. Every
# run appends one line to deploy-history.log (git-ignored). See DEPLOYMENT.md.
#
# Never prints a secret: the owner password is read from .env.production and
# reaches only the one-off migration container, through the environment.
set -euo pipefail

ENV_FILE=".env.production"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml)
HISTORY="deploy-history.log"
HEALTH_TIMEOUT=60
export ENV_FILE
export BACKUP_DIR="${BACKUP_DIR:-/var/backups/accessa}"

TARGET=""
OLD_COMMIT=""
NEW_COMMIT=""
BACKUP_FILE=""
STEP="start"
RESULT=""

say() { echo "==> $*"; }

# A value from .env.production (without surrounding quotes); empty if missing.
env_value() {
    local value
    value="$(grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- | tr -d '\r')" || true
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    printf '%s' "$value"
}

finish() {
    local status=$?
    if [ -z "$RESULT" ]; then
        RESULT=$([ "$status" -eq 0 ] && echo "ok" || echo "FAILED at $STEP")
    fi
    printf '%s %s -> %s %s (%s)\n' "$(date -u +%FT%TZ)" \
        "${OLD_COMMIT:0:7}" "${NEW_COMMIT:-${OLD_COMMIT:0:7}}" "$RESULT" "${TARGET:-?}" >> "$HISTORY"
    # A refusal changed nothing; any other failure after the backup gets the hint.
    if [ "$status" -ne 0 ] && [ -n "$BACKUP_FILE" ] && [ "${RESULT#refused}" = "$RESULT" ]; then
        cat >&2 <<EOF

!! Update failed ($RESULT).
!! Previous version: $OLD_COMMIT
!! Backup taken before this update: $BACKUP_FILE
!! To roll back:
!!   git checkout $OLD_COMMIT && dc build && dc up -d
!! If the new version already ran migrations the old code cannot handle, restore
!! that backup as described in DEPLOYMENT.md, section 8 (Real restore).
EOF
    fi
}

main() {
    TARGET="${1:-thesis}"
    cd "$(dirname "$0")/.."
    OLD_COMMIT="$(git rev-parse HEAD)"
    trap finish EXIT

    STEP="checks"
    [ -f "$ENV_FILE" ] || { RESULT="refused: no $ENV_FILE"; echo "$ENV_FILE not found in $(pwd)" >&2; exit 1; }
    if [ -n "$(git status --porcelain)" ]; then
        RESULT="refused: local changes"
        echo "The working tree has local changes; commit, stash or remove them first:" >&2
        git status --short >&2
        exit 1
    fi
    local domain
    domain="$(env_value ACCESSA_DOMAIN)"
    [ -n "$domain" ] || { RESULT="refused: ACCESSA_DOMAIN not set"; echo "ACCESSA_DOMAIN is not set in $ENV_FILE" >&2; exit 1; }

    STEP="backup"
    say "Backup"
    deploy/backup/backup.sh
    # shellcheck disable=SC2012  # file names are written by backup.sh
    BACKUP_FILE="$(ls -1t "$BACKUP_DIR"/accessa-*.dump | head -n 1)"

    STEP="git"
    say "Fetching and checking out $TARGET"
    git fetch --tags origin
    if git show-ref --verify --quiet "refs/remotes/origin/$TARGET"; then
        git checkout --quiet "$TARGET"
        git pull --ff-only origin "$TARGET"
    elif git show-ref --verify --quiet "refs/tags/$TARGET"; then
        git -c advice.detachedHead=false checkout --quiet --detach "refs/tags/$TARGET"
    else
        RESULT="refused: unknown branch or tag $TARGET"
        echo "$TARGET is neither a branch on origin nor a tag" >&2
        exit 1
    fi
    NEW_COMMIT="$(git rev-parse --short HEAD)"
    echo "old: $(git log -1 --format='%h %s' "$OLD_COMMIT")"
    echo "new: $(git log -1 --format='%h %s' HEAD)"

    STEP="build"
    say "Building images"
    "${COMPOSE[@]}" build

    STEP="migrations"
    say "Migrations (schema owner, one-off container)"
    local owner_pw
    owner_pw="$(env_value ACCESSA_OWNER_PASSWORD)"
    [ -n "$owner_pw" ] || { echo "ACCESSA_OWNER_PASSWORD is not set in $ENV_FILE" >&2; exit 1; }
    # The URL is in the environment of this one command only (not on any command
    # line, so not in ps output); -e NAME without a value hands it to the one-off
    # container. The running backend never gets it.
    MIGRATION_DATABASE_URL="postgresql+psycopg://accessa_owner:${owner_pw}@postgres:5432/accessa" \
        "${COMPOSE[@]}" run --rm -e MIGRATION_DATABASE_URL backend alembic upgrade head
    unset owner_pw

    STEP="restart"
    say "Starting the new version"
    "${COMPOSE[@]}" up -d

    STEP="health check"
    say "Waiting for https://$domain/api/health"
    local deadline=$((SECONDS + HEALTH_TIMEOUT))
    until curl -fsS --max-time 5 "https://$domain/api/health" 2>/dev/null | grep -Eq '"status" *: *"ok"'; do
        if [ "$SECONDS" -ge "$deadline" ]; then
            RESULT="FAILED: health check"
            echo "https://$domain/api/health did not return {\"status\":\"ok\"} within ${HEALTH_TIMEOUT}s." >&2
            echo "Check: dc ps, dc logs --tail=100 backend caddy" >&2
            exit 1
        fi
        sleep 3
    done
    echo "healthy"

    STEP="prune"
    docker image prune -f

    say "Updated ${OLD_COMMIT:0:7} -> $NEW_COMMIT"
}

# Everything runs inside main(), which bash reads completely before running it:
# the pull may replace this file without affecting the run in progress.
main "$@"
