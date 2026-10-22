# Deploying Accessa on Railway

Three services in one Railway project:

| Service | Source | What runs |
|---|---|---|
| **Postgres** | Railway PostgreSQL template | the database |
| **backend** | repo root: `Dockerfile`, `railway.json` | FastAPI on uvicorn, healthcheck `GET /health` |
| **frontend** | `frontend/`: `Dockerfile`, `Caddyfile`, `railway.json` | Vite build served by Caddy, SPA fallback to `index.html` |

Secrets live only in Railway variables (and your password manager). Nothing in this
repository contains a real password or key.

---

## 0. Prerequisites

- The `thesis` branch pushed to GitHub, and the GitHub repo connected to Railway.
- Railway CLI, logged in: `npm i -g @railway/cli` (or `brew install railway`), then `railway login`.
- `psql` locally (`brew install libpq`), or Docker (a `postgres:16` container can run psql, see step 2).
- Python 3 locally, to generate secrets.

## 1. Generate the secrets (locally, once)

Run these and store each value in your password manager. Do not commit them, paste
them into files in the repo, or share them in chat.

```bash
python3 -c "import secrets; print(secrets.token_hex(24))"         # ACCESSA_OWNER_PASSWORD
python3 -c "import secrets; print(secrets.token_hex(24))"         # ACCESSA_APP_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(64))"     # JWT_SECRET_KEY
pip install cryptography && \
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # MFA_ENCRYPTION_KEY
```

Hex passwords need no escaping inside connection URLs. Losing `MFA_ENCRYPTION_KEY`
makes every enrolled MFA secret unreadable (all users would need an admin MFA reset),
so keep it safe.

## 2. Create the project, the database and the database roles

1. Railway dashboard: **New Project → Deploy PostgreSQL**. Rename the service to
   `Postgres` if it has another name. The default database is `railway` (variable
   `PGDATABASE` of the Postgres service).
2. The template's own `DATABASE_URL` is the **superuser** connection. The backend never
   uses it.
3. Copy `DATABASE_PUBLIC_URL` from **Postgres → Variables** (the public TCP proxy) and
   create the two roles with `scripts/railway_db_roles.sql`, run as that superuser.
   The passwords are typed without echo and passed as psql variables, never written
   into a file:

   ```bash
   read -rs DB_SUPERUSER_URL;      # paste DATABASE_PUBLIC_URL, Enter
   read -rs OWNER_PW;              # paste ACCESSA_OWNER_PASSWORD, Enter
   read -rs APP_PW;                # paste ACCESSA_APP_PASSWORD, Enter
   psql "$DB_SUPERUSER_URL" -v ON_ERROR_STOP=1 \
        -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" \
        -f scripts/railway_db_roles.sql
   ```

   Without a local psql, from the repo root:

   ```bash
   docker run --rm -i postgres:16 psql "$DB_SUPERUSER_URL" -v ON_ERROR_STOP=1 \
        -v owner_pw="$OWNER_PW" -v app_pw="$APP_PW" -f - < scripts/railway_db_roles.sql
   ```

   Expected last line: `Roles ready. Next: run the migrations as accessa_owner`.
   The script creates `accessa_owner` (owns the database and the `public` schema, **no**
   `CREATEDB`) and `accessa_app` (SELECT/INSERT/UPDATE/DELETE on tables the owner
   creates, USAGE/SELECT on sequences, via default privileges). Running it again only
   updates the passwords.
4. `unset DB_SUPERUSER_URL APP_PW` (keep `OWNER_PW` for step 4 or read it again then).

## 3. Backend service

1. **New → GitHub Repo →** this repository. Rename the service to `backend`.
2. **Settings:**
   - Branch: `thesis`.
   - Root Directory: empty (repository root).
   - Config file path: `/railway.json` (Dockerfile build, healthcheck `/health`).
   - **Networking → Generate Domain.** If asked for a port, use the one Railway shows
     for `PORT` (the container listens on `$PORT`). Note the URL, e.g.
     `https://accessa-backend-production.up.railway.app`.
3. **Variables** (Raw Editor; replace the `<…>` parts):

   ```
   DATABASE_URL=postgresql+psycopg://accessa_app:<ACCESSA_APP_PASSWORD>@postgres.railway.internal:5432/railway
   JWT_SECRET_KEY=<JWT_SECRET_KEY>
   MFA_ENCRYPTION_KEY=<MFA_ENCRYPTION_KEY>
   CORS_ORIGINS=https://<frontend domain, set in step 6>
   OPENAI_API_KEY=<your OpenAI key>
   OPENAI_MODEL=gpt-4o-mini
   APP_ENV=production
   # optional, raises GitHub's limit for the AI review from 60 to 5,000 requests/hour:
   # GITHUB_TOKEN=<fine-grained token, public repositories, read-only>
   ```

   - `DATABASE_URL` uses the **application role** and the private hostname
     `postgres.railway.internal`, and must start with `postgresql+psycopg://`.
   - **Do not set `MIGRATION_DATABASE_URL` on this service.** The backend refuses to
     start in production when it is set, so the owner credentials never live on a
     running service.
   - `CLIENT_IP_HEADER=X-Real-IP` is already set in the Dockerfile (see "Client IP" below).
4. Deploy. The first deploy is healthy even before migrations: `/health` does not touch
   the database.

## 4. Migrations (as accessa_owner, only for that one command)

From the repo, link the CLI to the project once, then run Alembic inside the running
backend container. `MIGRATION_DATABASE_URL` is set for that single command only; it is
not stored on the service:

```bash
railway link          # choose the project and the production environment
read -rs OWNER_PW     # paste ACCESSA_OWNER_PASSWORD, Enter (if not still set)
railway ssh -s backend -- sh -c "cd /app && MIGRATION_DATABASE_URL='postgresql+psycopg://accessa_owner:${OWNER_PW}@postgres.railway.internal:5432/railway' alembic upgrade head"
unset OWNER_PW
```

`${OWNER_PW}` is expanded by your local shell (your shell history keeps only the
placeholder), and the URL exists only in the environment of that one remote process.

Then create the five roles (junior, mid, senior, lead, admin). This runs as the
application role, through the service's own `DATABASE_URL`:

```bash
railway ssh -s backend -- python -m backend.core.seed_roles
```

Repeat the migration command after every deploy that adds a migration. Never run
`backend.core.seed_admin` or `scripts/seed_demo.py` in production (`seed_demo.py`
refuses non-localhost URLs anyway).

Optional check, with the superuser URL from step 2:

```sql
SELECT has_table_privilege('accessa_app','audit_logs','UPDATE')  AS app_can_update_audit,   -- false
       has_table_privilege('accessa_app','audit_logs','DELETE')  AS app_can_delete_audit,   -- false
       has_table_privilege('accessa_app','audit_logs','INSERT')  AS app_can_insert_audit,   -- true
       has_table_privilege('accessa_app','alembic_version','SELECT') AS app_reads_alembic;  -- false
```

Migration `5d4a194aa17b` makes `audit_logs` append-only for `accessa_app` (it revokes
UPDATE, DELETE and TRUNCATE) and fails if `accessa_app` does not exist, which is why
step 2 comes first.

After this, the Postgres **public TCP proxy** (`DATABASE_PUBLIC_URL`) is no longer
needed: remove it under **Postgres → Settings → Networking**, and add it back only for
maintenance.

## 5. Frontend service

1. **New → GitHub Repo →** the same repository. Rename the service to `frontend`.
2. **Settings:**
   - Branch: `thesis`.
   - Root Directory: `frontend`.
   - Config file path: `/frontend/railway.json`.
   - **Networking → Generate Domain** (port: the one Railway shows for `PORT`). Note
     the URL, e.g. `https://accessa-frontend-production.up.railway.app`.
3. **Variables:**

   ```
   VITE_API_URL=https://<backend domain from step 3>
   ```

   This is a **build** variable: it is compiled into the bundle and into the
   Content-Security-Policy (`connect-src`), so the frontend must be **redeployed**
   whenever the backend URL changes. The build fails if it is missing. No secrets in
   `VITE_` variables: they are public.
4. Deploy. Caddy serves `dist/` on `$PORT`, falls back to `index.html` for client
   routes (`/w/<slug>`, `/requests/7`, …) and sends, as HTTP headers: the same
   Content-Security-Policy as `vite.config.js` (generated from `frontend/csp.config.js`,
   including `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`,
   `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and
   `Strict-Transport-Security: max-age=31536000`.

## 6. Connect the two

Set the backend's `CORS_ORIGINS` to the frontend URL (no trailing slash; several
origins are comma-separated) and let the backend redeploy:

```
CORS_ORIGINS=https://accessa-frontend-production.up.railway.app
```

## 7. Create the first workspace

`seed_demo.py` is for localhost only. In production every workspace starts with the
sign-up page:

1. Open `https://<frontend domain>/signup`.
2. Enter the workspace name, its address (slug, e.g. `acme`), your name, e-mail and a
   password (at least 8 characters). You become the workspace's first admin.
3. **Continue: set up two-factor authentication.** Scan the QR code with an
   authenticator app (or type the key), enter the 6-digit code. MFA is mandatory; the
   app cannot be used before this step.
4. Share `https://<frontend domain>/w/<slug>` with your team and create their accounts
   under **User Management**. Each person changes the initial password at first
   login, then sets up MFA.
5. Create a **second admin** early: an admin cannot reset their own MFA, and admin
   requests need a second admin to approve them.

Sign-up is open to anyone who can reach the page (it can only create a new
workspace, never join an existing one). Restrict or remove it if that is not wanted
for the deployment.

## 8. Verify

```bash
B=https://<backend domain>; F=https://<frontend domain>
curl -s $B/health                          # {"status":"ok"}
curl -sI $B/health | grep -iE "content-security|strict-transport|x-frame"
curl -sI $F/       | grep -iE "content-security|strict-transport|x-frame|referrer|nosniff"
curl -s -o /dev/null -w "%{http_code}\n" $F/w/<slug>   # 200 (SPA fallback)
```

**Client IP and spoofing check.** Send a failed login with fake headers, then look at
the newest *Failed Login* entry in the Audit Log (as admin):

```bash
curl -s -X POST $B/auth/login -H "Content-Type: application/json" \
     -H "X-Real-IP: 203.0.113.99" -H "X-Forwarded-For: 198.51.100.99" \
     -d '{"workspace_slug":"<slug>","email":"nobody@example.com","password":"x"}'
```

The IP shown must be **your real public IP**, not `203.0.113.99` or
`198.51.100.99`. If it shows `203.0.113.99`, Railway's edge did not overwrite
`X-Real-IP`: remove the header trust (set `CLIENT_IP_HEADER=` empty on the backend
service) and investigate before relying on per-IP rate limits.

## Client IP behind Railway's edge

- Railway's edge proxy sets `X-Real-IP` to the client's remote IP and
  `X-Forwarded-Proto` to `https` (Railway docs, *Public Networking → Specs & Limits*).
  It does not document how it treats a client-supplied `X-Forwarded-For`.
- The backend therefore trusts **only `X-Real-IP`**, and only when
  `CLIENT_IP_HEADER=X-Real-IP` is set (done in the Dockerfile):
  `backend/core/proxy.py` puts that value, if it is a valid IP address, into the
  request's client address, which the rate limiter and the audit log use.
  `X-Forwarded-For` is never read. uvicorn runs with `--no-proxy-headers`, so its own
  `X-Forwarded-For` handling is off.
- `X-Forwarded-Proto: https` marks the request as HTTPS, so the backend sends HSTS.
- This relies on every request reaching the backend through Railway's edge (only the
  edge is public). Do not expose the container port another way.

## Variables reference

| Service | Variable | Required | Notes |
|---|---|---|---|
| backend | `DATABASE_URL` | yes | `postgresql+psycopg://accessa_app:…@postgres.railway.internal:5432/railway` |
| backend | `JWT_SECRET_KEY` | yes | ≥ 32 bytes, e.g. `secrets.token_urlsafe(64)` |
| backend | `MFA_ENCRYPTION_KEY` | yes | Fernet key; keep a backup |
| backend | `CORS_ORIGINS` | yes | the frontend URL(s), comma-separated |
| backend | `OPENAI_API_KEY`, `OPENAI_MODEL` | yes | AI review; model must support JSON schema output |
| backend | `APP_ENV` | yes | `production` (HSTS, strict CSP on `/docs`, refuses `MIGRATION_DATABASE_URL`) |
| backend | `GITHUB_TOKEN` | no | read-only token for public repositories |
| backend | `MIGRATION_DATABASE_URL` | **never** | only inline in the migration command (step 4) |
| backend | `CLIENT_IP_HEADER` | set by Dockerfile | `X-Real-IP` |
| frontend | `VITE_API_URL` | yes (build) | the backend URL; redeploy after changing it |
