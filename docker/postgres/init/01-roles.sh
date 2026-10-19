#!/bin/bash
# Creates the two Accessa database roles (runs once, on an empty data volume).
#
#   accessa_owner  owns the database and schema; Alembic migrations run as this role
#                  (MIGRATION_DATABASE_URL). CREATEDB lets the test suite create a
#                  throwaway test database.
#   accessa_app    the running application (DATABASE_URL). Gets SELECT/INSERT/UPDATE/DELETE
#                  on tables the owner creates, and USAGE on sequences. The audit_logs
#                  table is narrowed to SELECT/INSERT by an Alembic migration, so the
#                  application can never rewrite or delete audit history.
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v db="$POSTGRES_DB" \
     -v owner_pw="$ACCESSA_OWNER_PASSWORD" \
     -v app_pw="$ACCESSA_APP_PASSWORD" <<'SQL'
CREATE ROLE accessa_owner LOGIN CREATEDB PASSWORD :'owner_pw';
CREATE ROLE accessa_app   LOGIN          PASSWORD :'app_pw';

ALTER DATABASE :"db" OWNER TO accessa_owner;
ALTER SCHEMA public OWNER TO accessa_owner;

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO accessa_app;
GRANT USAGE ON SCHEMA public TO accessa_app;

-- Privileges for every table/sequence that accessa_owner (i.e. Alembic) creates later.
ALTER DEFAULT PRIVILEGES FOR ROLE accessa_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO accessa_app;
ALTER DEFAULT PRIVILEGES FOR ROLE accessa_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO accessa_app;
SQL
