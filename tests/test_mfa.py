"""MFA with TOTP (SEC-14): login, enrolment, enforcement, reset, storage, audit."""
import re
from datetime import timedelta
from unittest.mock import patch

import pyotp
import pytest
from fastapi.routing import APIRoute
import jwt  # PyJWT

from backend.core import mfa
from backend.core.dependencies import get_current_user
from backend.core.security import ALGORITHM, SECRET_KEY, create_access_token
from backend.core.timeutils import utc_now
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.user import User

PASSWORD = "Password123"
USER_AGENT = "MfaTest/1.0"
T0 = 1_800_000_000.0  # a fixed point in time, at the start of a 30 s step
INVALID = {"detail": "Invalid or expired code"}


def _claims(token):
    """Claims without verifying signature or expiry (inspection only)."""
    return jwt.decode(token, options={"verify_signature": False})


def _fake_hash(p):
    return f"TESTHASH:{p}"


@pytest.fixture(autouse=True)
def fake_bcrypt():
    with patch("backend.api.auth.verify_password", side_effect=lambda p, h: h == _fake_hash(p)), \
         patch("backend.api.auth.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.verify_password", side_effect=lambda p, h: h == _fake_hash(p)):
        yield


@pytest.fixture
def clock(monkeypatch):
    """The TOTP clock; set clock.t to move time."""
    class Clock:
        t = T0
    monkeypatch.setattr(mfa, "now", lambda: Clock.t)
    return Clock


@pytest.fixture
def people(db, create_role, create_user):
    roles = {name: create_role(db, name, level=lvl) for name, lvl in
             [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]}
    users = {name: create_user(db, role=roles[role], label=name)
             for name, role in [("admin", "admin"), ("admin2", "admin"), ("mid", "mid"), ("junior", "junior")]}
    for user in users.values():
        user.hashed_password = _fake_hash(PASSWORD)
    db.commit()
    users["roles"] = roles
    return users


def _enrol(db, user, secret=None):
    """Enrol directly in the database (the API path is tested separately)."""
    secret = secret or pyotp.random_base32()
    user.mfa_secret_encrypted = mfa.encrypt_secret(secret)
    user.mfa_enabled = True
    db.commit()
    return secret


def _code(secret, t):
    return pyotp.TOTP(secret).at(t)


def _h(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}


def _login(client, user, password=PASSWORD):
    client.app.dependency_overrides.pop(get_current_user, None)  # real tokens
    return client.post("/auth/login", headers={"User-Agent": USER_AGENT},
                       json={"workspace_slug": "default-test", "email": user.email, "password": password})


def _pending(client, user):
    body = _login(client, user).json()
    assert body["mfa_required"] is True
    return body["mfa_token"]


def _verify(client, token, code):
    return client.post("/auth/mfa/verify", headers=_h(token), json={"code": code})


def _audit(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


# --- login with MFA ------------------------------------------------------------------------------

def test_login_without_code_gives_no_access_token(client, db, people, clock):
    _enrol(db, people["mid"])
    response = _login(client, people["mid"])

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] is None
    assert body["mfa_required"] is True and body["mfa_token"]
    claims = _claims(body["mfa_token"])
    assert claims["type"] == "mfa_pending"
    assert claims["exp"] - claims.get("iat", utc_now().timestamp()) <= 5 * 60 + 5
    assert _audit(db, "LOGIN_SUCCESS") == []  # not logged in until the code is accepted


def test_valid_code_returns_a_working_access_token(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    response = _verify(client, _pending(client, people["mid"]), _code(secret, T0))

    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    assert _claims(token)["type"] == "access"
    assert client.get("/change-requests/", headers=_h(token)).status_code == 200
    assert len(_audit(db, "LOGIN_SUCCESS")) == 1


@pytest.mark.parametrize("offset", [-30, 30], ids=["previous-step", "next-step"])
def test_codes_one_step_off_are_accepted_for_clock_drift(client, db, people, clock, offset):
    secret = _enrol(db, people["mid"])
    assert _verify(client, _pending(client, people["mid"]), _code(secret, T0 + offset)).status_code == 200


@pytest.mark.parametrize("code_time, label", [
    (T0 - 60, "expired (two steps old)"),
    (T0 + 60, "out of window (two steps ahead)"),
    (T0 - 3600, "an hour old"),
])
def test_codes_outside_the_window_fail(client, db, people, clock, code_time, label):
    secret = _enrol(db, people["mid"])
    response = _verify(client, _pending(client, people["mid"]), _code(secret, code_time))
    assert (response.status_code, response.json()) == (401, INVALID), label


@pytest.mark.parametrize("code", ["000000", "12345", "1234567", "abcdef", "", " 123456"])
def test_wrong_or_malformed_codes_fail_with_the_generic_error(client, db, people, clock, code):
    secret = _enrol(db, people["mid"])
    if code == _code(secret, T0):
        pytest.skip("random secret produced this code")
    response = _verify(client, _pending(client, people["mid"]), code)
    assert (response.status_code, response.json()) == (401, INVALID)


def test_a_code_cannot_be_used_twice(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    code = _code(secret, T0)
    assert _verify(client, _pending(client, people["mid"]), code).status_code == 200

    # Same code, new login, still inside its 90 s window.
    clock.t = T0 + 20
    response = _verify(client, _pending(client, people["mid"]), code)
    assert (response.status_code, response.json()) == (401, INVALID)
    # An older step than the last accepted one is refused too.
    response = _verify(client, _pending(client, people["mid"]), _code(secret, T0 - 30))
    assert response.status_code == 401
    # The next step works.
    assert _verify(client, _pending(client, people["mid"]), _code(secret, T0 + 30)).status_code == 200


def test_expired_pending_token_fails(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    claims = _claims(token)
    claims["exp"] = int((utc_now() - timedelta(seconds=1)).timestamp())
    expired = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)

    response = _verify(client, expired, _code(secret, T0))
    assert (response.status_code, response.json()) == (401, INVALID)


def test_tampered_or_foreign_tokens_fail(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    claims = _claims(token)

    for bad in (
        jwt.encode({**claims, "jti": "guessed"}, SECRET_KEY, algorithm=ALGORITHM),       # unknown jti
        jwt.encode(claims, "another-secret", algorithm=ALGORITHM),                       # wrong signature
        jwt.encode({**claims, "sub": str(people["junior"].id)}, SECRET_KEY, algorithm=ALGORITHM),
        create_access_token({"sub": claims["sub"], "workspace": claims["workspace"]}),  # access token
        "not-a-token",
    ):
        response = _verify(client, bad, _code(secret, T0))
        assert (response.status_code, response.json()) == (401, INVALID)
    assert client.post("/auth/mfa/verify", json={"code": _code(secret, T0)}).status_code == 401  # no token


def test_a_new_login_replaces_the_previous_pending_token(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    first = _pending(client, people["mid"])
    second = _pending(client, people["mid"])
    assert _verify(client, first, _code(secret, T0)).status_code == 401
    assert _verify(client, second, _code(secret, T0)).status_code == 200


def test_pending_token_works_only_once(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    assert _verify(client, token, _code(secret, T0)).status_code == 200
    clock.t = T0 + 30
    assert _verify(client, token, _code(secret, T0 + 30)).status_code == 401


def test_deactivated_user_cannot_finish_the_login(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    people["mid"].is_active = False
    db.commit()
    assert _verify(client, token, _code(secret, T0)).json() == INVALID


def test_mfa_pending_token_is_rejected_by_every_other_endpoint(client, db, people, clock):
    _enrol(db, people["admin"])
    token = _pending(client, people["admin"])
    public = {("POST", "/auth/login"), ("POST", "/auth/signup"), ("GET", "/"), ("GET", "/health"),
              ("POST", "/auth/mfa/verify")}

    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if (method, route.path) in public:
                continue
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            response = client.request(method, path, headers=_h(token), json={})
            assert response.status_code == 401, (method, route.path, response.status_code)
            checked += 1
    assert checked > 30


# --- 5 wrong codes ---------------------------------------------------------------------------------

def test_five_wrong_codes_invalidate_the_pending_token(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    wrong = "000000" if _code(secret, T0) != "000000" else "111111"

    for _ in range(5):
        assert _verify(client, token, wrong).json() == INVALID
    response = _verify(client, token, _code(secret, T0))  # correct now, but too late
    assert (response.status_code, response.json()) == (401, INVALID)

    db.expire_all()
    assert db.get(User, people["mid"].id).mfa_pending_jti is None
    failed = _audit(db, "MFA_FAILED")
    assert [e.severity for e in failed[:5]] == ["medium"] * 4 + ["high"]
    assert "invalidated" in failed[4].details

    # A fresh login gets 5 more tries with its own token (the account count stays at 5).
    db.expire_all()
    assert db.get(User, people["mid"].id).mfa_failed_attempts == 5
    assert _verify(client, _pending(client, people["mid"]), _code(secret, T0)).status_code == 200


def test_four_wrong_codes_still_allow_the_right_one(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    wrong = "000000" if _code(secret, T0) != "000000" else "111111"
    for _ in range(4):
        _verify(client, token, wrong)
    assert _verify(client, token, _code(secret, T0)).status_code == 200


# --- account lock after 10 consecutive wrong codes -----------------------------------------------------

def _wrong(secret):
    return "000000" if _code(secret, T0) != "000000" else "111111"


def _fail(client, token, secret, times):
    for _ in range(times):
        assert _verify(client, token, _wrong(secret)).json() == INVALID


def _attempts(db, user):
    db.expire_all()
    return db.get(User, user.id).mfa_failed_attempts


def test_a_new_login_does_not_reset_the_wrong_code_count(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    _fail(client, _pending(client, people["mid"]), secret, 3)
    _pending(client, people["mid"])
    assert _attempts(db, people["mid"]) == 3


def test_wrong_codes_spread_over_several_logins_lock_the_account(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    for wrong_codes in (4, 4, 1):  # 9 in a row, over three logins
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)
    assert _audit(db, "MFA_LOCKED") == []

    _fail(client, _pending(client, people["mid"]), secret, 1)  # the 10th
    [locked] = _audit(db, "MFA_LOCKED")
    assert locked.severity == "high" and "15 minutes" in locked.details and "10 consecutive" in locked.details
    assert (locked.ip_address, locked.user_agent) == ("testclient", USER_AGENT)
    db.expire_all()
    until = db.get(User, people["mid"].id).mfa_locked_until
    assert until.timestamp() == T0 + 15 * 60

    # While locked even the right code gets the generic error, after a new login too.
    response = _verify(client, _pending(client, people["mid"]), _code(secret, T0))
    assert (response.status_code, response.json()) == (401, INVALID)
    assert "locked" in _audit(db, "MFA_FAILED")[-1].details
    assert _audit(db, "LOGIN_SUCCESS") == []


def test_lock_expires_after_15_minutes(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    for wrong_codes in (5, 5):
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)

    clock.t = T0 + 15 * 60 - 1
    assert _verify(client, _pending(client, people["mid"]), _code(secret, clock.t)).json() == INVALID

    clock.t = T0 + 15 * 60
    response = _verify(client, _pending(client, people["mid"]), _code(secret, clock.t))
    assert response.status_code == 200, response.text
    db.expire_all()
    user = db.get(User, people["mid"].id)
    assert (user.mfa_failed_attempts, user.mfa_locked_until) == (0, None)


def test_after_the_lock_expires_the_next_wrong_code_locks_again(client, db, people, clock):
    # The count is reset only by a successful verify or an admin reset.
    secret = _enrol(db, people["mid"])
    for wrong_codes in (5, 5):
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)
    clock.t = T0 + 15 * 60
    _fail(client, _pending(client, people["mid"]), secret, 1)
    assert len(_audit(db, "MFA_LOCKED")) == 2
    db.expire_all()
    assert db.get(User, people["mid"].id).mfa_locked_until.timestamp() == clock.t + 15 * 60


def test_a_successful_verify_resets_the_counter(client, db, people, clock):
    secret = _enrol(db, people["mid"])
    for wrong_codes in (5, 4):
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)
    assert _attempts(db, people["mid"]) == 9
    assert _verify(client, _pending(client, people["mid"]), _code(secret, T0)).status_code == 200
    assert _attempts(db, people["mid"]) == 0

    clock.t = T0 + 30
    for wrong_codes in (5, 4):  # 9 more: 18 in total, but never 10 in a row
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)
    assert _audit(db, "MFA_LOCKED") == []
    assert _verify(client, _pending(client, people["mid"]), _code(secret, clock.t)).status_code == 200


def test_admin_reset_clears_the_lock(client, db, people, clock, login_user):
    secret = _enrol(db, people["mid"])
    for wrong_codes in (5, 5):
        _fail(client, _pending(client, people["mid"]), secret, wrong_codes)
    _enrol(db, people["admin"])

    login_user(people["admin"])
    assert client.patch(f"/users/{people['mid'].id}/mfa-reset").status_code == 200
    db.expire_all()
    user = db.get(User, people["mid"].id)
    assert (user.mfa_failed_attempts, user.mfa_locked_until, user.mfa_enabled) == (0, None, False)

    # Re-enrol, then the next login works right away (still within the old lock period).
    login_user(people["mid"])
    new_secret = client.post("/auth/mfa/setup").json()["secret"]
    assert client.post("/auth/mfa/confirm", json={"code": _code(new_secret, T0)}).status_code == 200
    clock.t = T0 + 30
    assert _verify(client, _pending(client, people["mid"]), _code(new_secret, clock.t)).status_code == 200


def test_verify_is_rate_limited_like_login(client, db, people, clock):
    _enrol(db, people["mid"])
    token = _pending(client, people["mid"])
    app.state.limiter.reset()
    app.state.limiter.enabled = True
    try:
        statuses = [_verify(client, token, "000000").status_code for _ in range(6)]
    finally:
        app.state.limiter.enabled = False
        app.state.limiter.reset()
    assert statuses[:5] == [401] * 5 and statuses[5] == 429


# --- enforcement and enrolment ---------------------------------------------------------------------

def test_user_without_mfa_is_blocked_until_enrolled_after_password_change(client, db, people, clock, login_user):
    login_user(people["admin"])
    created = client.post("/users/", json={"full_name": "New Person", "email": "new@example.com",
                                           "password": "Initial123", "role_id": people["roles"]["mid"].id})
    assert created.status_code == 200, created.text
    new_user = db.query(User).filter(User.email == "new@example.com").one()

    # No code is asked before MFA exists: the login gives an access token directly.
    login = _login(client, new_user, "Initial123").json()
    assert login["mfa_required"] is False and login["must_change_password"] is True
    token = login["access_token"]

    # 1. Password change first: even MFA setup is blocked until then.
    for method, path in [("POST", "/auth/mfa/setup"), ("GET", "/change-requests/")]:
        blocked = client.request(method, path, headers=_h(token))
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "password_change_required"
    assert client.put("/users/me/password", headers=_h(token), json={
        "current_password": "Initial123", "new_password": "Changed123", "confirm_password": "Changed123",
    }).status_code == 200

    # 2. Then MFA: everything else answers mfa_setup_required.
    for method, path in [("GET", "/change-requests/"), ("GET", "/users/reviewers"), ("PUT", "/users/me"),
                         ("GET", "/users/me/stats"), ("POST", "/change-requests/")]:
        blocked = client.request(method, path, headers=_h(token), json={"full_name": "x"})
        assert blocked.status_code == 403, path
        assert blocked.json()["detail"]["code"] == "mfa_setup_required"
    assert client.get("/users/me", headers=_h(token)).status_code == 200

    setup = client.post("/auth/mfa/setup", headers=_h(token))
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    uri = setup.json()["otpauth_uri"]
    assert uri.startswith("otpauth://totp/Accessa:new%40example.com?") and "issuer=Accessa" in uri
    assert f"secret={secret}" in uri
    db.expire_all()
    assert db.get(User, new_user.id).mfa_enabled is False  # not until confirmed

    assert client.post("/auth/mfa/confirm", headers=_h(token), json={"code": "000000"}).status_code == 400
    confirmed = client.post("/auth/mfa/confirm", headers=_h(token), json={"code": _code(secret, T0)})
    assert confirmed.json() == {"mfa_enabled": True}

    # 3. Now the same session may use Accessa, and the next login asks for a code.
    assert client.get("/change-requests/", headers=_h(token)).status_code == 200
    assert _login(client, new_user, "Changed123").json()["mfa_required"] is True


def test_confirm_code_cannot_be_reused_for_the_first_login(client, db, people, clock, login_user):
    login_user(people["mid"])
    secret = client.post("/auth/mfa/setup").json()["secret"]
    code = _code(secret, T0)
    assert client.post("/auth/mfa/confirm", json={"code": code}).status_code == 200
    assert _verify(client, _pending(client, people["mid"]), code).status_code == 401


def test_setup_and_confirm_cannot_be_called_once_mfa_is_enabled(client, db, people, clock, login_user):
    _enrol(db, people["mid"])
    login_user(people["mid"])
    setup = client.post("/auth/mfa/setup")
    assert (setup.status_code, setup.json()) == (409, {"detail": "MFA is already enabled"})
    assert client.post("/auth/mfa/confirm", json={"code": "123456"}).status_code == 409


def test_confirm_needs_setup_first(client, db, people, clock, login_user):
    login_user(people["mid"])
    assert client.post("/auth/mfa/confirm", json={"code": "123456"}).status_code == 400


def test_calling_setup_again_before_confirming_replaces_the_secret(client, db, people, clock, login_user):
    login_user(people["mid"])
    first = client.post("/auth/mfa/setup").json()["secret"]
    second = client.post("/auth/mfa/setup").json()["secret"]
    assert first != second
    assert client.post("/auth/mfa/confirm", json={"code": _code(first, T0)}).status_code == 400
    assert client.post("/auth/mfa/confirm", json={"code": _code(second, T0)}).status_code == 200


def test_access_tokens_without_a_type_are_rejected(client, db, people):
    # Tokens issued before MFA existed carry no "type" claim.
    _enrol(db, people["mid"])
    claims = {"sub": str(people["mid"].id), "workspace": str(people["mid"].workspace.public_id),
              "exp": int((utc_now() + timedelta(minutes=5)).timestamp())}
    legacy = jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)
    client.app.dependency_overrides.pop(get_current_user, None)
    assert client.get("/users/me", headers=_h(legacy)).status_code == 401


# --- secret storage ------------------------------------------------------------------------------------

def test_secret_is_stored_encrypted_and_never_returned_after_confirmation(client, db, people, clock, login_user):
    login_user(people["mid"])
    secret = client.post("/auth/mfa/setup").json()["secret"]

    db.expire_all()
    stored = db.get(User, people["mid"].id).mfa_secret_encrypted
    assert stored and secret not in stored
    assert mfa.decrypt_secret(stored) == secret

    client.post("/auth/mfa/confirm", json={"code": _code(secret, T0)})
    login_user(people["admin"])
    _enrol(db, people["admin"])
    responses = [
        client.get("/users/me"), client.get("/users/"), client.get(f"/users/{people['mid'].id}/details"),
        client.get("/users/reviewers"), client.post("/auth/mfa/setup"), client.get("/audit-logs/"),
    ]
    login_user(people["mid"])
    responses += [client.get("/users/me"), client.post("/auth/mfa/setup")]
    for response in responses:
        assert secret not in response.text
        assert "mfa_secret" not in response.text
    me = client.get("/users/me").json()
    assert me["mfa_enabled"] is True


def test_undecryptable_secret_never_verifies(client, db, people, clock):
    _enrol(db, people["mid"])
    people["mid"].mfa_secret_encrypted = "not-a-fernet-token"
    db.commit()
    assert _verify(client, _pending(client, people["mid"]), "123456").json() == INVALID


# --- admin reset ---------------------------------------------------------------------------------------

def test_admin_can_reset_another_users_mfa(client, db, people, clock, login_user):
    secret = _enrol(db, people["mid"])
    pending = _pending(client, people["mid"])  # a sign-in waiting for its code
    _enrol(db, people["admin"])

    login_user(people["admin"])
    response = client.patch(f"/users/{people['mid'].id}/mfa-reset", headers={"User-Agent": USER_AGENT})
    assert response.status_code == 200, response.text
    assert response.json()["mfa_enabled"] is False

    db.expire_all()
    mid = db.get(User, people["mid"].id)
    assert (mid.mfa_enabled, mid.mfa_secret_encrypted, mid.mfa_last_used_step, mid.mfa_pending_jti) == (
        False, None, None, None)
    assert _verify(client, pending, _code(secret, T0)).status_code == 401  # waiting sign-in revoked

    # Next login: no code (nothing enrolled), then only enrolment is open.
    login = _login(client, mid).json()
    assert login["mfa_required"] is False
    blocked = client.get("/change-requests/", headers=_h(login["access_token"]))
    assert blocked.json()["detail"]["code"] == "mfa_setup_required"
    assert client.post("/auth/mfa/setup", headers=_h(login["access_token"])).status_code == 200


def test_admin_can_reset_another_admin(client, db, people, login_user):
    _enrol(db, people["admin2"])
    login_user(people["admin"])
    assert client.patch(f"/users/{people['admin2'].id}/mfa-reset").status_code == 200


def test_admin_cannot_reset_their_own_mfa(client, db, people, login_user):
    _enrol(db, people["admin"])
    login_user(people["admin"])
    response = client.patch(f"/users/{people['admin'].id}/mfa-reset")
    assert (response.status_code, response.json()) == (400, {"detail": "You cannot reset your own MFA"})
    db.expire_all()
    assert db.get(User, people["admin"].id).mfa_enabled is True
    assert _audit(db, "MFA_RESET") == []


@pytest.mark.parametrize("actor", ["mid", "junior"])
def test_non_admins_cannot_reset_mfa(client, db, people, login_user, actor):
    _enrol(db, people["admin2"])
    login_user(people[actor])
    assert client.patch(f"/users/{people['admin2'].id}/mfa-reset").status_code == 403
    db.expire_all()
    assert db.get(User, people["admin2"].id).mfa_enabled is True


def test_reset_is_workspace_scoped(client, db, people, login_user, create_workspace, create_user):
    other = create_workspace(db, "Other", "other-ws")
    foreign = create_user(db, role=people["roles"]["mid"], label="foreign", workspace=other)
    _enrol(db, foreign)

    login_user(people["admin"])
    response = client.patch(f"/users/{foreign.id}/mfa-reset")
    assert (response.status_code, response.json()) == (404, {"detail": "User not found"})
    db.expire_all()
    assert db.get(User, foreign.id).mfa_enabled is True
    assert _audit(db, "MFA_RESET") == []


# --- audit -------------------------------------------------------------------------------------------------

def test_audit_entries_have_client_info_and_no_codes_or_secrets(client, db, people, clock, login_user):
    used_codes = []
    # Enrol via the API (MFA_ENROLLED, plus one MFA_FAILED for a wrong code).
    login_user(people["mid"])
    secret = client.post("/auth/mfa/setup", headers={"User-Agent": USER_AGENT}).json()["secret"]
    client.post("/auth/mfa/confirm", headers={"User-Agent": USER_AGENT}, json={"code": "000000"})
    used_codes.append(_code(secret, T0))
    client.post("/auth/mfa/confirm", headers={"User-Agent": USER_AGENT}, json={"code": used_codes[-1]})

    # Login: one wrong code (MFA_FAILED), then the right one (MFA_VERIFIED).
    clock.t = T0 + 30
    token = _pending(client, people["mid"])
    _verify(client, token, "999999")
    used_codes.append(_code(secret, clock.t))
    _verify(client, token, used_codes[-1])

    # Reset by an admin (MFA_RESET).
    _enrol(db, people["admin"])
    login_user(people["admin"])
    client.patch(f"/users/{people['mid'].id}/mfa-reset", headers={"User-Agent": USER_AGENT})

    entries = {action: _audit(db, action) for action in ("MFA_ENROLLED", "MFA_VERIFIED", "MFA_FAILED", "MFA_RESET")}
    assert all(entries.values()), {k: len(v) for k, v in entries.items()}
    assert entries["MFA_RESET"][0].user_id == people["admin"].id
    assert entries["MFA_RESET"][0].entity_id == people["mid"].id
    assert entries["MFA_ENROLLED"][0].user_id == people["mid"].id

    for entry in [e for group in entries.values() for e in group]:
        assert (entry.ip_address, entry.user_agent) == ("testclient", USER_AGENT), entry.action
        stored = " ".join(filter(None, [entry.details, entry.old_value, entry.new_value]))
        assert secret not in stored
        for code in used_codes + ["000000", "999999"]:
            assert code not in stored, (entry.action, stored)


def test_failed_audit_write_does_not_enable_mfa(client, db, app_db_engine, people, clock, login_user):
    from sqlalchemy import text
    login_user(people["mid"])
    secret = client.post("/auth/mfa/setup").json()["secret"]
    with patch("backend.api.mfa.log_action", side_effect=RuntimeError("audit store down")):
        with pytest.raises(RuntimeError):
            client.post("/auth/mfa/confirm", json={"code": _code(secret, T0)})
    with app_db_engine.connect() as conn:
        assert conn.execute(text("SELECT mfa_enabled FROM users WHERE id = :id"),
                            {"id": people["mid"].id}).scalar() is False
