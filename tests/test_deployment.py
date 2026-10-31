"""Deployment behaviour: /health, client IP behind Caddy, production guard, update script."""
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app, check_production_environment
from backend.models.audit_log import AuditLog


def test_health_needs_no_auth_and_returns_no_data(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-frame-options"] == "DENY"


def _failed_login(client, headers):
    client.post("/auth/login", headers=headers,
                json={"workspace_slug": "default-test", "email": "ghost@example.com", "password": "x"})


def _last_login_ip(db):
    return db.query(AuditLog).filter(AuditLog.action == "LOGIN_FAILED").order_by(AuditLog.id.desc()).first().ip_address


def test_client_supplied_forwarding_headers_are_ignored_by_the_app(client, db):
    # The app itself never reads X-Real-IP / X-Forwarded-For: only uvicorn's
    # --proxy-headers does, and only for connections from Caddy (below).
    _failed_login(client, {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"})
    assert _last_login_ip(db) == "testclient"


def test_spoofed_headers_do_not_escape_the_rate_limit(client, db):
    body = {"workspace_slug": "default-test", "email": "ghost@example.com", "password": "x"}
    app.state.limiter.reset()
    app.state.limiter.enabled = True
    try:
        codes = [client.post("/auth/login", json=body,
                             headers={"X-Forwarded-For": f"198.51.100.{i}", "X-Real-IP": f"203.0.113.{i}"}).status_code
                 for i in range(7)]
    finally:
        app.state.limiter.enabled = False
        app.state.limiter.reset()
    assert codes[-1] == 429


def test_hsts_only_over_https_in_production(db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app, base_url="https://testserver") as https_client:
        secure = https_client.get("/health")
    with TestClient(app) as http_client:
        # A client-supplied X-Forwarded-Proto does not make plain http count as https.
        plain = http_client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert secure.headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in plain.headers


# --- client IP in production: uvicorn --proxy-headers, trusting only Caddy -------------

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "docker-compose.prod.yml").read_text()


def _caddy_ip() -> str:
    trusted = re.search(r"--forwarded-allow-ips=\$\{CADDY_IP:-([0-9.]+)\}", COMPOSE).group(1)
    caddy = re.search(r"ipv4_address: \$\{CADDY_IP:-([0-9.]+)\}", COMPOSE).group(1)
    assert trusted == caddy
    return caddy


def test_backend_trusts_proxy_headers_only_from_caddy():
    assert "- --proxy-headers" in COMPOSE
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert '"--proxy-headers"' in dockerfile and "--no-proxy-headers" not in dockerfile
    # No second, header-based way of setting the client address.
    assert "CLIENT_IP_HEADER" not in COMPOSE + dockerfile


@pytest.mark.parametrize("peer, expected", [
    ("caddy", ("203.0.113.7", "https")),       # Caddy's X-Forwarded-For/-Proto are applied
    ("172.30.0.3", ("172.30.0.3", "http")),     # anyone else on the network: ignored
])
def test_uvicorn_proxy_headers_with_the_compose_setting(peer, expected):
    import asyncio

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    caddy = _caddy_ip()
    seen = {}

    async def inner(scope, receive, send):
        seen["client"], seen["scheme"] = scope["client"][0], scope["scheme"]

    middleware = ProxyHeadersMiddleware(inner, trusted_hosts=caddy)
    scope = {"type": "http", "scheme": "http", "client": (caddy if peer == "caddy" else peer, 40000),
             "headers": [(b"x-forwarded-for", b"203.0.113.7"), (b"x-forwarded-proto", b"https")]}
    asyncio.run(middleware(scope, None, None))
    assert (seen["client"], seen["scheme"]) == expected


def test_production_refuses_migration_credentials(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://owner:pw@db/x")
    with pytest.raises(RuntimeError, match="MIGRATION_DATABASE_URL"):
        check_production_environment()
    monkeypatch.delenv("MIGRATION_DATABASE_URL")
    check_production_environment()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql+psycopg://owner:pw@db/x")
    check_production_environment()


# --- deploy/update.sh (checked as text) -------------------------------------------------

UPDATE_SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "update.sh"


def _script_code() -> str:
    """The script without comment lines, so comments cannot satisfy the checks."""
    lines = UPDATE_SCRIPT.read_text().splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_update_script_is_executable():
    assert os.access(UPDATE_SCRIPT, os.X_OK)


def test_update_script_pulls_fast_forward_only():
    code = _script_code()
    assert "git pull --ff-only" in code
    assert re.search(r"git pull(?! --ff-only)", code) is None


def test_update_script_backs_up_before_pulling():
    code = _script_code()
    assert "deploy/backup/backup.sh" in code
    assert code.index("deploy/backup/backup.sh") < code.index("git fetch") < code.index("git pull")


def test_update_script_passes_migration_url_by_name_only():
    code = _script_code()
    # -e NAME without a value: the URL comes from the environment of that one
    # command, never from the command line.
    assert re.search(r"run --rm -e MIGRATION_DATABASE_URL backend alembic upgrade head", code)
    assert "-e MIGRATION_DATABASE_URL=" not in code
    assert "export MIGRATION_DATABASE_URL" not in code


def test_update_script_never_traces_commands():
    code = UPDATE_SCRIPT.read_text()
    assert "set -euo pipefail" in code
    assert re.search(r"set -[a-z]*x|set -o xtrace|bash -x", code) is None
