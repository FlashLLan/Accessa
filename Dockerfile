# Accessa backend (FastAPI) for Railway. See DEPLOYMENT.md.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Railway's edge proxy sets X-Real-IP to the client address; the app trusts
    # that header only (never X-Forwarded-For). backend/core/proxy.py
    CLIENT_IP_HEADER=X-Real-IP

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Application and migrations only: no tests, scripts, frontend or local files.
COPY backend ./backend
COPY database ./database
COPY alembic ./alembic
COPY alembic.ini .

RUN useradd --system --uid 10001 --no-create-home accessa
USER accessa

# --no-proxy-headers: uvicorn's own proxy handling reads X-Forwarded-For; the
# client address comes from X-Real-IP via TrustedProxyHeadersMiddleware instead.
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]
