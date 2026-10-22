"""Deployment behaviour: /health, client IP behind Railway's edge, production guard."""
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


def test_without_client_ip_header_setting_no_header_is_trusted(client, db, monkeypatch):
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    _failed_login(client, {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"})
    assert _last_login_ip(db) == "testclient"


def test_x_real_ip_is_the_client_address_behind_the_edge(client, db, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    _failed_login(client, {"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1, 10.0.0.1"})
    assert _last_login_ip(db) == "203.0.113.7"


def test_x_forwarded_for_is_never_used(client, db, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    _failed_login(client, {"X-Forwarded-For": "198.51.100.1"})
    assert _last_login_ip(db) == "testclient"


@pytest.mark.parametrize("value", ["not-an-ip", "203.0.113.7, 198.51.100.1", "", "<script>"])
def test_invalid_header_values_are_ignored(client, db, monkeypatch, value):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    _failed_login(client, {"X-Real-IP": value})
    assert _last_login_ip(db) == "testclient"


def test_ipv6_client_address(client, db, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    _failed_login(client, {"X-Real-IP": "2001:db8::1"})
    assert _last_login_ip(db) == "2001:db8::1"


def test_rate_limit_is_per_real_client(client, db, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    body = {"workspace_slug": "default-test", "email": "ghost@example.com", "password": "x"}
    app.state.limiter.reset()
    app.state.limiter.enabled = True
    try:
        first = [client.post("/auth/login", json=body, headers={"X-Real-IP": "203.0.113.7"}).status_code
                 for _ in range(6)]
        other = client.post("/auth/login", json=body, headers={"X-Real-IP": "203.0.113.8"}).status_code
        # Changing X-Forwarded-For does not escape the limit.
        spoof = client.post("/auth/login", json=body,
                            headers={"X-Real-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"}).status_code
    finally:
        app.state.limiter.enabled = False
        app.state.limiter.reset()
    assert first[-1] == 429 and other == 401 and spoof == 429


def test_forwarded_proto_https_enables_hsts_in_production(db, monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "X-Real-IP")
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as http_client:  # plain http to the app, https at the edge
        response = http_client.get("/health", headers={"X-Forwarded-Proto": "https"})
        plain = http_client.get("/health")
    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in plain.headers


def test_forwarded_proto_is_ignored_without_the_setting(db, monkeypatch):
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as http_client:
        response = http_client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert "strict-transport-security" not in response.headers


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
