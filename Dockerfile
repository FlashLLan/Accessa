# Accessa backend (FastAPI). Built by docker-compose.prod.yml; see DEPLOYMENT.md.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

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

# The client address and scheme come from X-Forwarded-For/-Proto only when the
# connection comes from an address in --forwarded-allow-ips (uvicorn's default:
# 127.0.0.1, i.e. nobody outside the container). docker-compose.prod.yml
# overrides this command with --forwarded-allow-ips=<Caddy's fixed address>.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
