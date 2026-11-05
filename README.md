# Accessa

Accessa is a web application for secure identity and access management with change
governance. Teams work in separate workspaces with role-based access (junior, mid,
senior, lead, admin) and mandatory multi-factor authentication. Changes to systems and
access are submitted as change requests and approved by a reviewer chosen according to
an approval matrix. A request can be linked to a GitHub pull request and given an
advisory AI review. Every significant action is recorded in an append-only audit log.
Accessa was built as a bachelor's thesis at Vilnius University Kaunas Faculty.

Live: **https://accessa.dev**

Backend: FastAPI, SQLAlchemy, PostgreSQL, Alembic. Frontend: React and Vite.

## Local setup

### Prerequisites

- Python 3.14
- Node.js 22
- Docker (with Docker Compose), for the local PostgreSQL

### 1. Configuration

```bash
cp .env.example .env
```

Replace every `change-me` value in `.env`. Generate the two keys with:

```bash
# JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"
# MFA_ENCRYPTION_KEY (needs the cryptography package, installed in step 3)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep `MFA_ENCRYPTION_KEY` safe: if it is lost or changed, every enrolled MFA secret becomes
unreadable. `.env` is never committed. The AI review also needs `OPENAI_API_KEY` and
`OPENAI_MODEL`; without them everything else still works.

### 2. Database

```bash
docker compose up -d
```

This starts PostgreSQL 16 and creates the schema owner role (used for migrations) and
the application role (used by the running backend).

### 3. Backend

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m backend.core.seed_roles
uvicorn backend.main:app --reload
```

The API runs at http://localhost:8000.

### 4. Frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The app runs at http://localhost:5173. It calls the API at http://localhost:8000. To use
another address, set `VITE_API_URL` in `frontend/.env`; see `frontend/.env.example`.

### 5. First account

Either:

- open http://localhost:5173/signup to create a workspace and its first admin, then set
  up MFA with an authenticator app; or
- create demo data (a workspace with users in every role, requests and reviews) with the
  backend running:

  ```bash
  python scripts/seed_demo.py --enrol-mfa
  ```

  This uses the password from `DEMO_PASSWORD` in `.env` and prints each user's TOTP
  setup key once at the end. Sign in at http://localhost:5173/w/demo.

## Tests

```bash
# Backend: needs the PostgreSQL container; TEST_DATABASE_URL is in .env
python -m pytest -q

# Frontend
cd frontend
npm test
npm run lint
```

The backend tests create and drop their own database, the one named in
`TEST_DATABASE_URL` (`accessa_test` in `.env.example`), and never touch the development data.

## Production

Deployment to a server with Docker Compose and Caddy (HTTPS) is described in
[DEPLOYMENT.md](DEPLOYMENT.md).
