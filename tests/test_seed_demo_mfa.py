"""scripts/seed_demo.py run in-process against the app (TestClient instead of HTTP)."""
import importlib.util
import re
import time
from pathlib import Path
from unittest.mock import patch

import pyotp
import pytest

from backend.core import mfa
from backend.core.dependencies import get_current_user
from backend.models.change_request import ChangeRequest
from backend.models.user import User

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"
spec = importlib.util.spec_from_file_location("seed_demo_mfa", SCRIPT)
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)

DEMO_PASSWORD = "Demo-pass-123"


def _fake_hash(p):
    return f"TESTHASH:{p}"


@pytest.fixture
def seeded_app(client, db, create_role, monkeypatch):
    for name, level in [("junior", 1), ("mid", 2), ("senior", 3), ("lead", 4), ("admin", 5)]:
        create_role(db, name, level=level)
    client.app.dependency_overrides.pop(get_current_user, None)  # the script uses real tokens
    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    monkeypatch.setattr(seed_demo.requests, "Session", lambda: client)
    with patch("backend.api.auth.verify_password", side_effect=lambda p, h: h == _fake_hash(p)), \
         patch("backend.api.auth.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.hash_password", side_effect=_fake_hash), \
         patch("backend.api.users.verify_password", side_effect=lambda p, h: h == _fake_hash(p)):
        yield client


def test_enrol_mfa_enrols_every_user_and_prints_working_keys_once(seeded_app, db, capsys, monkeypatch):
    seed_demo.main(["--enrol-mfa"])
    out = capsys.readouterr().out

    keys = dict(re.findall(r"^\s+(\S+@test\.com)\s+\w+\s+\S+\s+MFA key: ([A-Z2-7]+)$", out, re.M))
    users = db.query(User).filter(User.email.like("%@test.com")).all()
    assert len(users) == 10 and set(keys) == {u.email for u in users}
    assert db.query(ChangeRequest).count() == 10

    for user in users:
        assert user.mfa_enabled is True
        # Stored encrypted only; printed once.
        assert keys[user.email] not in user.mfa_secret_encrypted
        assert mfa.decrypt_secret(user.mfa_secret_encrypted) == keys[user.email]
        assert out.count(keys[user.email]) == 1

    # Every printed key completes a real login (one step later than enrolment,
    # since the enrolment code cannot be used again).
    later = time.time() + 30
    monkeypatch.setattr(mfa, "now", lambda: later)
    for user in users:
        login = seeded_app.post("/auth/login", json={
            "workspace_slug": "demo", "email": user.email, "password": DEMO_PASSWORD}).json()
        assert login["mfa_required"] is True
        verified = seeded_app.post("/auth/mfa/verify",
                                   headers={"Authorization": f"Bearer {login['mfa_token']}"},
                                   json={"code": pyotp.TOTP(keys[user.email]).at(later)})
        assert verified.status_code == 200, (user.email, verified.text)


def test_without_flag_only_the_workspace_and_admin_are_created(seeded_app, db, capsys):
    seed_demo.main([])
    out = capsys.readouterr().out

    users = db.query(User).filter(User.email.like("%@test.com")).all()
    assert [u.email for u in users] == ["admin@test.com"]
    assert users[0].mfa_enabled is False and users[0].mfa_secret_encrypted is None
    assert db.query(ChangeRequest).count() == 0
    assert "MFA key" not in out and "--enrol-mfa" in out
