"""Security headers on every API response (XSS hardening, layer 1)."""
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from backend.main import app

EXPECTED = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}

# A route that fails with an unhandled exception, registered for these tests only.
_boom = APIRouter()


@_boom.get("/__test__/boom")
def boom():
    raise RuntimeError("unhandled")


@pytest.fixture(scope="module", autouse=True)
def boom_route():
    app.include_router(_boom)
    yield
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/__test__/boom"]


def _assert_security_headers(response):
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, (name, response.status_code, response.headers)


def test_headers_on_a_normal_response(client):
    response = client.get("/")
    assert response.status_code == 200
    _assert_security_headers(response)
    assert "strict-transport-security" not in response.headers


@pytest.mark.parametrize("method, path, kwargs, status", [
    ("get", "/users/me", {}, 401),                                                     # no token
    ("get", "/users/me", {"headers": {"Authorization": "Bearer nope"}}, 401),          # bad token
    ("get", "/does-not-exist", {}, 404),
    ("post", "/auth/login", {"json": {}}, 422),                                        # validation error
    ("post", "/auth/login", {"json": {"workspace_slug": "x", "email": "a@b.c", "password": "p"}}, 401),
    ("delete", "/", {}, 405),
])
def test_headers_on_error_responses(client, db, method, path, kwargs, status):
    response = client.request(method.upper(), path, **kwargs)
    assert response.status_code == status
    _assert_security_headers(response)


def test_headers_on_an_authorization_error(client, db, create_role, create_user, login_user):
    junior = create_user(db, role=create_role(db, "junior", level=1), label="junior")
    login_user(junior)
    response = client.get("/audit-logs/")
    assert response.status_code == 403
    _assert_security_headers(response)


def test_headers_on_a_rate_limited_response(client, db):
    app.state.limiter.reset()
    app.state.limiter.enabled = True
    try:
        for _ in range(6):
            response = client.post("/auth/login", json={"workspace_slug": "x", "email": "a@b.c", "password": "p"})
    finally:
        app.state.limiter.enabled = False
        app.state.limiter.reset()
    assert response.status_code == 429
    _assert_security_headers(response)


def test_headers_on_an_unhandled_server_error(db):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/__test__/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    _assert_security_headers(response)


def test_headers_on_a_cors_preflight(client):
    response = client.options("/users/me", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert response.status_code == 200
    _assert_security_headers(response)


def test_no_hsts_over_https_outside_production(db, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/")
    assert "strict-transport-security" not in response.headers


def test_no_hsts_over_plain_http_in_production(db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app, base_url="http://testserver") as client:
        response = client.get("/")
    assert "strict-transport-security" not in response.headers
    _assert_security_headers(response)


def test_hsts_over_https_in_production(db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app, base_url="https://testserver") as client:
        ok = client.get("/")
        error = client.get("/users/me")
    for response in (ok, error):
        assert response.headers["strict-transport-security"] == "max-age=31536000"
        _assert_security_headers(response)


def test_docs_page_has_no_csp_in_development_only(db, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    with TestClient(app) as client:
        docs = client.get("/docs")
        schema = client.get("/openapi.json")
    assert docs.status_code == 200
    assert "content-security-policy" not in docs.headers
    assert docs.headers["x-frame-options"] == "DENY" and docs.headers["x-content-type-options"] == "nosniff"
    _assert_security_headers(schema)

    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as client:
        _assert_security_headers(client.get("/docs"))
