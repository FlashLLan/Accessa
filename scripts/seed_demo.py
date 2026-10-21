"""Create demo data through the HTTP API only.

    python scripts/seed_demo.py [--api-url http://localhost:8000] [--workspace-slug demo]

Every record is created the way a real user would create it (sign-up, admin
creates users, login, forced password change, create/submit/approve/reject/
escalate/delegate/apply, comments, Git context, AI review), so it passes the
current validation, permission and approval rules and produces its own audit
entries. Nothing is written to the database directly.

Passwords are never hard-coded: every demo user gets the password from the
DEMO_PASSWORD setting (environment or .env; the API requires >= 8 characters).
Admin-created users first get a random initial password and change it to
DEMO_PASSWORD through the API, as the forced password change requires.
The credentials are printed once, at the end.

Refuses to run unless the API URL points at localhost. Needs a running backend,
the five roles, and a workspace slug that is still free. From an empty database:

    python scripts/reset_local_dev_db.py --no-seed   # stop the backend first
    python -m backend.core.seed_roles
    uvicorn backend.main:app                          # start the backend again
    python scripts/seed_demo.py
"""
import argparse
import os
import secrets
import sys
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
RATE_LIMIT_WAIT_SECONDS = 61  # login and sign-up are limited to 5/minute per client

ADMIN = ("admin@test.com", "Alice Admin")
# Two users per role, so every role has a second reviewer (delegation goes to the
# same role; a lead's request can only be approved by another lead).
USERS = [
    # (email, full name, role)
    ("admin2@test.com", "Adam Admin", "admin"),
    ("lead@test.com", "Laura Lead", "lead"),
    ("lead2@test.com", "Leo Lead", "lead"),
    ("senior@test.com", "Sam Senior", "senior"),
    ("senior2@test.com", "Sofia Senior", "senior"),
    ("mid@test.com", "Mike Mid", "mid"),
    ("mid2@test.com", "Maya Mid", "mid"),
    ("junior@test.com", "Julia Junior", "junior"),
    ("junior2@test.com", "Jack Junior", "junior"),
]


def assert_local_api(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(f"REFUSED: API URL must be http(s), got '{url}'.")
    if (parsed.hostname or "") not in LOCAL_HOSTS:
        raise SystemExit(f"REFUSED: API URL host is '{parsed.hostname}'. Demo data is only seeded on localhost.")


def demo_password() -> str:
    password = os.getenv("DEMO_PASSWORD")
    if not password:
        raise SystemExit("REFUSED: set DEMO_PASSWORD (in .env or the environment); see .env.example.")
    if len(password) < 8:
        raise SystemExit("REFUSED: DEMO_PASSWORD must be at least 8 characters (the API's password rule).")
    return password


class Api:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "accessa-seed-demo/1.0"

    def call(self, method: str, path: str, token: str | None = None, expected: int = 200, **kwargs):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        while True:
            response = self.http.request(method, self.base + path, headers=headers, timeout=30, **kwargs)
            if response.status_code != 429:
                break
            print(f"  rate limited on {path}; waiting {RATE_LIMIT_WAIT_SECONDS}s ...")
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
        if response.status_code != expected:
            raise SystemExit(f"FAILED: {method} {path} -> {response.status_code} {response.text}")
        return response.json() if response.content else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--workspace-slug", default="demo")
    parser.add_argument("--workspace-name", default="Demo Team")
    parser.add_argument("--frontend-url", default="http://localhost:5173", help="only used for the printed login link")
    args = parser.parse_args()

    assert_local_api(args.api_url)
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    password = demo_password()
    api = Api(args.api_url)
    slug = args.workspace_slug
    credentials: list[tuple[str, str, str]] = []

    # --- workspace and its first admin (sign-up) --------------------------------
    print(f"Signing up workspace '{slug}' ...")
    admin_password = password
    signup = api.call("POST", "/auth/signup", json={
        "workspace_name": args.workspace_name, "workspace_slug": slug,
        "full_name": ADMIN[1], "email": ADMIN[0], "password": admin_password,
    })
    tokens = {ADMIN[0]: signup["access_token"]}
    credentials.append((ADMIN[0], "admin", admin_password))
    admin = tokens[ADMIN[0]]

    roles = {r["name"]: r["id"] for r in api.call("GET", "/roles/", admin)}
    ids = {ADMIN[0]: api.call("GET", "/users/me", admin)["id"]}

    # --- admin creates the other users; each logs in and sets a new password ----
    for email, full_name, role in USERS:
        print(f"Creating {email} ({role}) ...")
        initial = secrets.token_urlsafe(12)
        created = api.call("POST", "/users/", admin, json={
            "full_name": full_name, "email": email, "password": initial, "role_id": roles[role],
        })
        ids[email] = created["id"]

        login = api.call("POST", "/auth/login", json={"workspace_slug": slug, "email": email, "password": initial})
        assert login["must_change_password"] is True
        final = password
        api.call("PUT", "/users/me/password", login["access_token"], json={
            "current_password": initial, "new_password": final, "confirm_password": final,
        })
        tokens[email] = login["access_token"]
        credentials.append((email, role, final))

    def token(email):
        return tokens[email]

    def create(author, title, risk, reviewer, *, description, target, environment="staging",
               request_type="configuration_change", git_context=None):
        body = {
            "title": title, "description": description, "request_type": request_type,
            "target_system": target, "environment": environment, "risk_level": risk,
            "assigned_reviewer_id": ids[reviewer],
        }
        if git_context:
            body["git_context"] = git_context
        return api.call("POST", "/change-requests/", token(author), json=body)["id"]

    def act(email, request_id, action, body=None):
        return api.call("POST", f"/change-requests/{request_id}/{action}", token(email), json=body)

    def comment(email, request_id, text):
        act(email, request_id, "comments", {"comment_text": text})

    print("Creating change requests ...")
    # 1. APPLIED: junior -> mid approves -> junior applies
    r1 = create("junior@test.com", "Rotate staging database credentials", "low", "mid@test.com",
                description="Rotate the read-only DB user password on staging.", target="staging-db",
                git_context={"provider": "github", "repository_name": "infra/secrets",
                             "branch_name": "rotate-staging-db", "target_branch": "main",
                             "pull_request_url": "https://github.com/example/infra/pull/101"})
    act("junior@test.com", r1, "submit")
    comment("mid@test.com", r1, "Checked the rotation runbook, looks fine.")
    act("mid@test.com", r1, "approve", {"decision_comment": "Low risk, approved."})
    act("junior@test.com", r1, "apply")

    # 2. REJECTED: mid -> senior rejects
    r2 = create("mid@test.com", "Open port 8080 on the public load balancer", "medium", "senior@test.com",
                description="Expose the debug endpoint for troubleshooting.", target="public-lb",
                environment="production", request_type="security_change")
    act("mid@test.com", r2, "submit")
    act("senior@test.com", r2, "reject", {"decision_comment": "Debug endpoints must not be public."})

    # 3. ESCALATED then REJECTED: junior (high) -> senior escalates to lead -> lead rejects
    r3 = create("junior@test.com", "Grant production write access to analytics team", "high", "senior@test.com",
                description="Analytics needs write access to the reporting schema.", target="prod-db",
                environment="production", request_type="access_change")
    act("junior@test.com", r3, "submit")
    act("senior@test.com", r3, "escalate", {"target_reviewer_id": ids["lead@test.com"],
                                            "comment": "Production write access needs a lead decision."})
    comment("lead@test.com", r3, "A read replica would cover this need.")
    act("lead@test.com", r3, "reject", {"decision_comment": "Use the read replica instead."})

    # 4. DELEGATED then APPLIED: junior (medium) -> senior delegates to senior2 -> approve -> apply
    r4 = create("junior@test.com", "Increase API worker count from 4 to 8", "medium", "senior@test.com",
                description="Traffic has doubled; scale the worker pool.", target="api-cluster",
                environment="production", request_type="resource_change")
    act("junior@test.com", r4, "submit")
    act("senior@test.com", r4, "delegate", {"target_reviewer_id": ids["senior2@test.com"],
                                            "comment": "Sofia owns the API cluster."})
    act("senior2@test.com", r4, "ai-review")
    act("senior2@test.com", r4, "approve", {"decision_comment": "Capacity checked."})
    act("junior@test.com", r4, "apply")

    # 5. Admin request (two-admin rule): admin -> admin2 approves -> admin applies
    r5 = create(ADMIN[0], "Enable SSO enforcement for all users", "high", "admin2@test.com",
                description="Require SSO for every login.", target="identity-provider",
                environment="production", request_type="administrative_change")
    act(ADMIN[0], r5, "submit")
    act("admin2@test.com", r5, "approve", {"decision_comment": "Second admin approval."})
    act(ADMIN[0], r5, "apply")

    # 6. APPROVED, awaiting apply: senior (high) -> lead approves
    r6 = create("senior@test.com", "Upgrade PostgreSQL 15 to 16", "high", "lead@test.com",
                description="Major version upgrade during the maintenance window.", target="prod-db",
                environment="production", request_type="deployment_change")
    act("senior@test.com", r6, "submit")
    act("lead@test.com", r6, "approve", {"decision_comment": "Approved for Saturday's window."})

    # 7. DELEGATED then REJECTED: junior2 -> mid delegates to mid2 -> mid2 rejects
    r7b = create("junior2@test.com", "Disable 2FA for the build service account", "low", "mid@test.com",
                 description="The CI bot cannot complete 2FA prompts.", target="ci-runner",
                 request_type="security_change")
    act("junior2@test.com", r7b, "submit")
    act("mid@test.com", r7b, "delegate", {"target_reviewer_id": ids["mid2@test.com"],
                                          "comment": "Maya handles CI accounts."})
    act("mid2@test.com", r7b, "reject", {"decision_comment": "Use a scoped deploy token instead of disabling 2FA."})

    # 8. Lead request approved by the second lead and applied
    r8 = create("lead@test.com", "Retire the legacy VPN gateway", "medium", "lead2@test.com",
                description="All teams have moved to the zero-trust proxy.", target="vpn-gateway",
                environment="production", request_type="deployment_change")
    act("lead@test.com", r8, "submit")
    act("lead2@test.com", r8, "approve", {"decision_comment": "Migration confirmed with all teams."})
    act("lead@test.com", r8, "apply")

    # 9. PENDING_REVIEW: mid -> senior
    r7 = create("mid@test.com", "Add rate limiting to the export endpoint", "low", "senior@test.com",
                description="Limit exports to 10 per minute per user.", target="api-gateway",
                request_type="code_change")
    act("mid@test.com", r7, "submit")

    # 10. DRAFT: junior, not submitted yet
    create("junior@test.com", "Clean up unused feature flags", "low", "mid@test.com",
           description="Remove 12 flags that have been on for 6 months.", target="feature-flags",
           environment="development", request_type="code_change")

    # --- summary -------------------------------------------------------------------
    print(f"\nDone. Workspace login: {args.frontend_url.rstrip('/')}/w/{slug}")
    print("\nCredentials (shown once; the password comes from DEMO_PASSWORD):")
    for email, role, password in credentials:
        print(f"  {email:<20} {role:<7} {password}")


if __name__ == "__main__":
    main()
