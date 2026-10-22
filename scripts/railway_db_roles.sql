-- Accessa database roles for Railway PostgreSQL (see DEPLOYMENT.md).
--
-- Same rights as docker/postgres/init/01-roles.sh, except that accessa_owner
-- gets NO CREATEDB in production (locally it is only needed by the test suite).
--
--   accessa_owner  owns the database and the public schema; Alembic migrations
--                  run as this role (MIGRATION_DATABASE_URL, migration command only).
--   accessa_app    the running backend (DATABASE_URL). SELECT/INSERT/UPDATE/DELETE
--                  on the tables accessa_owner creates, USAGE/SELECT on sequences.
--                  Migration 5d4a194aa17b then revokes UPDATE/DELETE/TRUNCATE on
--                  audit_logs (append-only) and all access to alembic_version; it
--                  fails if accessa_app does not exist, so run this file first.
--
-- Run once as the Railway superuser (postgres), BEFORE the first migration.
-- Passwords are psql variables, never written into this file:
--
--   psql "$DATABASE_PUBLIC_URL" -v ON_ERROR_STOP=1 \
--        -v owner_pw="$ACCESSA_OWNER_PASSWORD" -v app_pw="$ACCESSA_APP_PASSWORD" \
--        -f scripts/railway_db_roles.sql
--
-- Safe to run again: existing roles only get their passwords updated.

\if :{?owner_pw}
\else
  \echo 'Set the owner password: -v owner_pw=...'
  \quit
\endif
\if :{?app_pw}
\else
  \echo 'Set the application password: -v app_pw=...'
  \quit
\endif

SELECT current_database() AS db \gset

-- Roles (created, or password updated if they already exist).
SELECT format('CREATE ROLE accessa_owner LOGIN NOCREATEDB NOCREATEROLE PASSWORD %L', :'owner_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'accessa_owner') \gexec
SELECT format('CREATE ROLE accessa_app LOGIN NOCREATEDB NOCREATEROLE PASSWORD %L', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'accessa_app') \gexec
ALTER ROLE accessa_owner LOGIN NOCREATEDB NOCREATEROLE PASSWORD :'owner_pw';
ALTER ROLE accessa_app   LOGIN NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';

-- The owner owns the database and the schema the tables live in.
ALTER DATABASE :"db" OWNER TO accessa_owner;
ALTER SCHEMA public OWNER TO accessa_owner;

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO accessa_app;
GRANT USAGE ON SCHEMA public TO accessa_app;

-- Privileges for every table/sequence accessa_owner (i.e. Alembic) creates later.
ALTER DEFAULT PRIVILEGES FOR ROLE accessa_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO accessa_app;
ALTER DEFAULT PRIVILEGES FOR ROLE accessa_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO accessa_app;

\echo 'Roles ready. Next: run the migrations as accessa_owner (DEPLOYMENT.md).'
