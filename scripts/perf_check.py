"""NFR-06 response-time check on the LOCAL stack.

NFR-06: main pages and API calls respond in under 2 seconds for a workspace of up
to 250 users.

    # backend running locally against the local database, from the repository root:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000
    # in a second terminal:
    python scripts/perf_check.py [--api-url http://127.0.0.1:8000] [--seed 6]

What it does:

1. Creates a fresh workspace ("perf-<timestamp>") directly in the database named
   by DATABASE_URL, as the application role: 250 users in all five roles, each
   with MFA already set up (a TOTP secret generated here, stored encrypted with
   MFA_ENCRYPTION_KEY like an enrolment through the API would); 2,000 change
   requests in all statuses spread over the users, reviewers chosen per the
   approval matrix; their approvals; about 5,000 comments and review actions
   (escalations and delegations); about 20,000 audit records. Bulk inserts are
   used because creating this through the API would take hours (login and MFA
   are rate-limited to 5 per minute).
2. Measures against the running backend with httpx, one call at a time:
   - 50 x login (POST /auth/login + POST /auth/mfa/verify with a TOTP code),
     50 different users, since a TOTP code is accepted only once;
   - 50 x GET /users/me;
   - 50 x request list: GET /change-requests/ as an admin (all 2,000 requests,
     the largest list);
   - 50 x request detail page: the four calls the page makes (request, approvals,
     comments, review actions), timed together, on 50 different requests;
   - 50 x review queue: GET /change-requests/ as the lead with the most assigned
     requests (the page filters the list in the browser);
   - 50 x user list page (admin): GET /users/ + GET /roles/;
   - 50 x audit log (admin): GET /audit-logs/ (every call also writes an
     "Audit Log Viewed" entry, as in normal use);
   - 20 x approve and 20 x escalate, each on its own pending request.
   One untimed warm-up call per read endpoint comes first. The detail and user
   list pages are timed as sequential calls; the browser runs them in parallel,
   so those figures are an upper bound.
3. Prints a table (calls, median, 95th percentile, maximum in ms, PASS/FAIL
   against 2,000 ms) and the machine and software versions. Exit code 1 if any
   endpoint fails.

Every login comes from a different client address (X-Forwarded-For, which a
local uvicorn trusts from 127.0.0.1 by default), so the login rate limit does
not stop the run. If uvicorn runs with --no-proxy-headers or is reached via
another address, logins get 429 and the script says so.

Guards (checked before connecting anywhere): the API URL and the DATABASE_URL
host must be localhost / 127.0.0.1 / ::1. The users' password is random for each
run and never printed or stored. The data stays in the local database (the audit
log is append-only); scripts/reset_local_dev_db.py clears it.

Needs: the five roles (python -m backend.core.seed_roles), .env with
DATABASE_URL, JWT_SECRET_KEY and MFA_ENCRYPTION_KEY (the same values the
running backend uses).
"""
import argparse
import math
import os
import platform
import random
import secrets
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pyotp
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
LIMIT_MS = 2000

ROLE_COUNTS = {"admin": 10, "lead": 30, "senior": 50, "mid": 70, "junior": 90}  # 250
REQUESTS = 2000
COMMENTS = 3500
REVIEW_ACTIONS = 1500
AUDIT_RECORDS = 20000
MEASURED_CALLS = 50
WRITE_CALLS = 20
# Share of the generated requests per status (before the 40 pending requests
# reserved for approve and escalate).
STATUS_WEIGHTS = {"draft": 10, "pending_review": 20, "approved": 30, "rejected": 10, "applied": 30}
CREATOR_WEIGHTS = {"junior": 40, "mid": 30, "senior": 20, "lead": 9, "admin": 1}
USER_AGENT = "accessa-perf-check/1.0"


def refuse(message: str) -> None:
    raise SystemExit(f"REFUSED: {message}")


def check_local(api_url: str) -> None:
    parsed = urlparse(api_url)
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "") not in LOCAL_HOSTS:
        refuse(f"API URL '{api_url}' is not on localhost.")
    raw = os.getenv("DATABASE_URL")
    if not raw:
        refuse("DATABASE_URL is not set (see .env.example).")
    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        refuse("DATABASE_URL is not a PostgreSQL URL.")
    if (url.host or "") not in LOCAL_HOSTS:
        refuse(f"DATABASE_URL host is '{url.host}'. This script only runs against a local database.")


# --- data -----------------------------------------------------------------------------

def build_workspace(rng: random.Random, slug: str):
    """Insert the workspace and its data; returns what the measurements need."""
    # Imported only after the guard: these modules read DATABASE_URL and the keys.
    from sqlalchemy import func, insert, select, text

    from backend.core import mfa
    from backend.core.security import hash_password
    from backend.models.approval import Approval
    from backend.models.audit_log import AuditLog
    from backend.models.change_request import ChangeRequest
    from backend.models.comment import Comment
    from backend.models.enums import (
        ApprovalDecision, EnvironmentType, RequestStatus, RequestType, ReviewActionType, RiskLevel,
    )
    from backend.models.review_action import ReviewAction
    from backend.models.role import Role
    from backend.models.user import User
    from backend.models.workspace import Workspace
    from backend.services.approval_service import APPROVAL_MATRIX
    from database.db import engine

    now = datetime.now(timezone.utc)
    password = secrets.token_urlsafe(18)
    password_hash = hash_password(password)  # one bcrypt hash, shared: same password for all

    def ago(days_max: float, days_min: float = 0.0) -> datetime:
        return now - timedelta(days=rng.uniform(days_min, days_max))

    with engine.begin() as conn:
        server_version = conn.execute(text("SHOW server_version")).scalar_one()
        roles = {name: (rid, level) for rid, name, level in conn.execute(select(Role.id, Role.name, Role.level))}
        missing = set(ROLE_COUNTS) - set(roles)
        if missing:
            refuse(f"roles missing: {', '.join(sorted(missing))}. Run: python -m backend.core.seed_roles")

        workspace_id = conn.execute(
            insert(Workspace).values(slug=slug, name=f"Performance check {slug[5:]}").returning(Workspace.id)
        ).scalar_one()

        # Users: MFA enabled with a secret generated here, the step counter empty.
        user_rows, secrets_by_index = [], []
        n = 0
        for role, count in ROLE_COUNTS.items():
            for i in range(1, count + 1):
                n += 1
                secret = mfa.new_secret()
                secrets_by_index.append(secret)
                user_rows.append({
                    "workspace_id": workspace_id, "full_name": f"Perf {role.capitalize()} {i:03d}",
                    "email": f"{role}{i:03d}@perf.example.com", "hashed_password": password_hash,
                    "role_id": roles[role][0], "must_change_password": False, "mfa_enabled": True,
                    "mfa_secret_encrypted": mfa.encrypt_secret(secret), "is_active": True,
                    "created_at": ago(400, 365),
                })
        ids = conn.execute(
            insert(User).returning(User.id, sort_by_parameter_order=True), user_rows
        ).scalars().all()
        users = []  # dicts: id, role, email, secret
        for row, uid, secret in zip(user_rows, ids, secrets_by_index):
            role = next(name for name, (rid, _) in roles.items() if rid == row["role_id"])
            users.append({"id": uid, "role": role, "email": row["email"], "secret": secret})
        by_role = {role: [u for u in users if u["role"] == role] for role in ROLE_COUNTS}
        role_of = {u["id"]: u["role"] for u in users}

        # Change requests, reviewers per the approval matrix.
        statuses = rng.choices(list(STATUS_WEIGHTS), weights=STATUS_WEIGHTS.values(),
                               k=REQUESTS - 2 * WRITE_CALLS)
        request_rows = []

        def request_row(creator, reviewer, risk, status, created):
            row = {
                "workspace_id": workspace_id, "title": f"Change {len(request_rows) + 1:04d}: {rng.choice(TITLES)}",
                "description": "Generated for the NFR-06 response-time check.",
                "request_type": rng.choice(list(RequestType)), "target_system": rng.choice(SYSTEMS),
                "environment": rng.choice(list(EnvironmentType)), "risk_level": RiskLevel(risk),
                "status": RequestStatus(status), "created_by": creator["id"],
                "assigned_reviewer_id": reviewer["id"], "created_at": created, "updated_at": created,
                "submitted_at": None, "closed_at": None,
            }
            if status != "draft":
                row["submitted_at"] = created + timedelta(hours=rng.uniform(0.1, 24))
                row["updated_at"] = row["submitted_at"]
            if status in ("approved", "rejected", "applied"):
                row["closed_at"] = row["submitted_at"] + timedelta(hours=rng.uniform(0.5, 72))
                row["updated_at"] = row["closed_at"]
            request_rows.append(row)

        for status in statuses:
            creator_role = rng.choices(list(CREATOR_WEIGHTS), weights=CREATOR_WEIGHTS.values())[0]
            creator = rng.choice(by_role[creator_role])
            risk = rng.choice(["low", "medium", "high"])
            pool = [u for r in APPROVAL_MATRIX[(creator_role, risk)] for u in by_role[r] if u["id"] != creator["id"]]
            request_row(creator, rng.choice(pool), risk, status, ago(365, 1))

        # Reserved pending requests: a junior's low-risk request, which mid, senior
        # and lead may approve. Approve: assigned to one lead. Escalate: assigned to
        # one mid, who escalates it to a senior.
        approver, escalator = by_role["lead"][0], by_role["mid"][0]
        for _ in range(WRITE_CALLS):
            request_row(rng.choice(by_role["junior"]), approver, "low", "pending_review", ago(2))
        for _ in range(WRITE_CALLS):
            request_row(rng.choice(by_role["junior"]), escalator, "low", "pending_review", ago(2))

        request_ids = conn.execute(
            insert(ChangeRequest).returning(ChangeRequest.id, sort_by_parameter_order=True), request_rows
        ).scalars().all()
        for row, rid in zip(request_rows, request_ids):
            row["id"] = rid
        generated = request_rows[: len(request_rows) - 2 * WRITE_CALLS]
        approve_ids = request_ids[-2 * WRITE_CALLS:-WRITE_CALLS]
        escalate_ids = request_ids[-WRITE_CALLS:]
        submitted = [r for r in generated if r["status"] != RequestStatus.DRAFT]

        # Decisions for closed requests.
        approvals = [{
            "change_request_id": r["id"], "reviewer_id": r["assigned_reviewer_id"],
            "decision": ApprovalDecision.REJECTED if r["status"] == RequestStatus.REJECTED else ApprovalDecision.APPROVED,
            "created_at": r["closed_at"],
        } for r in generated if r["closed_at"] is not None]
        conn.execute(insert(Approval), approvals)

        # Comments by the requester or the reviewer (generated text only).
        comments = []
        for _ in range(COMMENTS):
            r = rng.choice(submitted)
            comments.append({
                "change_request_id": r["id"], "user_id": rng.choice([r["created_by"], r["assigned_reviewer_id"]]),
                "comment_text": rng.choice(COMMENT_TEXTS), "created_at": r["submitted_at"] + timedelta(minutes=rng.uniform(1, 600)),
            })
        conn.execute(insert(Comment), comments)

        # Review actions that ended at the current reviewer: an escalation from a
        # lower role, or a delegation within the same role.
        level = {role: lvl for role, (_, lvl) in roles.items()}
        actions = []
        while len(actions) < REVIEW_ACTIONS:
            r = rng.choice(submitted)
            target_role = role_of[r["assigned_reviewer_id"]]
            if target_role == "admin":
                continue
            kind = rng.choice([ReviewActionType.ESCALATE, ReviewActionType.DELEGATE])
            if kind == ReviewActionType.ESCALATE:
                actor_roles = [x for x in ROLE_COUNTS if x != "admin" and level[x] < level[target_role]]
            else:
                actor_roles = [target_role]
            actors = [u for x in actor_roles for u in by_role[x]
                      if u["id"] not in (r["created_by"], r["assigned_reviewer_id"])]
            if not actors:
                continue
            actions.append({
                "change_request_id": r["id"], "actor_id": rng.choice(actors)["id"], "action_type": kind,
                "target_reviewer_id": r["assigned_reviewer_id"], "comment": None,
                "created_at": r["submitted_at"] + timedelta(minutes=rng.uniform(1, 600)),
            })
        conn.execute(insert(ReviewAction), actions)

        # Audit records: the event mix of normal use, technical details only.
        audit = []
        for _ in range(AUDIT_RECORDS):
            actor = rng.choice(users)
            action, entity_type, severity = rng.choices(AUDIT_EVENTS, weights=[e[3] for e in AUDIT_EVENTS])[0][:3]
            entity_id, request_id, details = None, None, AUDIT_DETAILS.get(action, "")
            if entity_type == "change_request":
                r = rng.choice(generated)
                entity_id = request_id = r["id"]
                details = details.format(reviewer=r["assigned_reviewer_id"], risk=r["risk_level"].value)
            elif entity_type == "user":
                entity_id = actor["id"] if action.startswith(("LOGIN", "MFA")) else rng.choice(users)["id"]
            audit.append({
                "workspace_id": workspace_id, "user_id": actor["id"], "actor_role": actor["role"],
                "action": action, "entity_type": entity_type, "entity_id": entity_id, "request_id": request_id,
                "details": details or None, "severity": severity, "created_at": ago(365),
                "ip_address": "127.0.0.1", "user_agent": USER_AGENT,
            })
        conn.execute(insert(AuditLog), audit)

        counts = {
            "users": len(users), "change_requests": len(request_rows), "approvals": len(approvals),
            "comments": len(comments), "review_actions": len(actions),
            "audit_logs": conn.execute(select(func.count()).select_from(AuditLog)
                                       .where(AuditLog.workspace_id == workspace_id)).scalar_one(),
        }
        status_counts = dict(conn.execute(
            select(ChangeRequest.status, func.count()).where(ChangeRequest.workspace_id == workspace_id)
            .group_by(ChangeRequest.status)
        ).all())

    # The lead with the most assigned requests: the fullest review queue (not the
    # approver, whose queue also holds the reserved requests).
    assigned = {}
    for r in request_rows:
        assigned[r["assigned_reviewer_id"]] = assigned.get(r["assigned_reviewer_id"], 0) + 1
    queue_lead = max(by_role["lead"][1:], key=lambda u: assigned.get(u["id"], 0))

    return {
        "password": password, "users": users, "by_role": by_role, "counts": counts,
        "status_counts": {s.value: c for s, c in status_counts.items()}, "server_version": server_version,
        "detail_ids": rng.sample([r["id"] for r in submitted], MEASURED_CALLS),
        "approve_ids": approve_ids, "escalate_ids": escalate_ids,
        "approver": approver, "escalator": escalator, "queue_lead": queue_lead,
        "queue_size": assigned.get(queue_lead["id"], 0),
    }


TITLES = ["Rotate service credentials", "Open firewall port for monitoring", "Raise database pool size",
          "Grant read access to billing logs", "Deploy release candidate", "Update TLS configuration",
          "Add on-call engineer to pager group", "Resize worker nodes", "Enable audit logging on bucket",
          "Remove stale VPN accounts"]
SYSTEMS = ["api-gateway", "billing-db", "k8s-prod", "vpn", "ci-runner", "object-storage", "monitoring"]
COMMENT_TEXTS = ["Looks fine to me.", "Please attach the rollback plan.", "Scheduled for the next window.",
                 "Checked the diff, no concerns.", "Can we limit this to staging first?", "Done on my side."]
# (action, entity type, severity, weight)
AUDIT_EVENTS = [
    ("LOGIN_SUCCESS", "user", "low", 30), ("MFA_VERIFIED", "user", "low", 25), ("LOGIN_FAILED", "user", "medium", 4),
    ("MFA_FAILED", "user", "medium", 2), ("REQUEST_CREATED", "change_request", "low", 8),
    ("REQUEST_SUBMITTED", "change_request", "medium", 7), ("REQUEST_APPROVED", "change_request", "high", 6),
    ("REQUEST_REJECTED", "change_request", "high", 2), ("REQUEST_APPLIED", "change_request", "high", 5),
    ("COMMENT_CREATED", "change_request", "low", 6), ("REQUEST_ESCALATED", "change_request", "medium", 1),
    ("REQUEST_DELEGATED", "change_request", "medium", 1), ("AUDIT_VIEWED", "audit_log", "low", 2),
    ("ROLE_CHANGED", "user", "high", 0.5), ("USER_CREATED", "user", "medium", 0.5),
]
AUDIT_DETAILS = {
    "LOGIN_SUCCESS": "User logged in", "MFA_VERIFIED": "MFA code accepted", "LOGIN_FAILED": "Failed login (wrong password)",
    "MFA_FAILED": "Wrong MFA code at login", "REQUEST_CREATED": "Created request assigned to reviewer_id={reviewer}",
    "REQUEST_SUBMITTED": "Submitted for review | risk_level={risk}", "REQUEST_APPROVED": "Approved | risk_level={risk} | commit=none",
    "REQUEST_REJECTED": "Rejected | risk_level={risk} | commit=none", "REQUEST_APPLIED": "Marked as applied",
    "COMMENT_CREATED": "Comment added", "REQUEST_ESCALATED": "Escalated to reviewer_id={reviewer}",
    "REQUEST_DELEGATED": "Delegated to reviewer_id={reviewer}", "AUDIT_VIEWED": "Admin viewed audit log",
    "ROLE_CHANGED": "Role changed from 'junior' to 'mid'", "USER_CREATED": "User created with role 'junior'",
}


# --- measurements ---------------------------------------------------------------------

class Client:
    def __init__(self, base_url: str, slug: str, password: str):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=60, headers={"User-Agent": USER_AGENT})
        self.slug, self.password = slug, password
        # A different client address per login (see the module docstring).
        base = secrets.randbelow(200) + 20
        self._addresses = (f"10.{base}.{i // 250}.{i % 250 + 1}" for i in range(10_000_000))

    def call(self, method: str, path: str, token: str | None = None, expected: int = 200, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = self.http.request(method, path, headers=headers, **kwargs)
        if response.status_code == 429:
            raise SystemExit(
                f"FAILED: {method} {path} was rate limited (429). Start the backend with uvicorn's default proxy "
                "headers (no --no-proxy-headers) and use --api-url http://127.0.0.1:8000."
            )
        if response.status_code != expected:
            raise SystemExit(f"FAILED: {method} {path} -> {response.status_code} {response.text[:300]}")
        return response

    def login(self, user: dict) -> str:
        """Password, then the TOTP code; both steps from the same new client address."""
        address = {"X-Forwarded-For": next(self._addresses)}
        step1 = self.call("POST", "/auth/login", headers=dict(address), json={
            "workspace_slug": self.slug, "email": user["email"], "password": self.password,
        }).json()
        if not step1.get("mfa_required"):
            raise SystemExit("FAILED: login did not ask for MFA; is the backend using the same database?")
        step2 = self.call("POST", "/auth/mfa/verify", token=step1["mfa_token"], headers=dict(address),
                          json={"code": pyotp.TOTP(user["secret"]).now()}).json()
        return step2["access_token"]


def timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def measure(client: Client, data: dict) -> list[tuple[str, list[float]]]:
    by_role = data["by_role"]
    admin, senior = by_role["admin"][0], by_role["senior"][0]
    special = {admin["id"], senior["id"], data["approver"]["id"], data["escalator"]["id"], data["queue_lead"]["id"]}
    login_users = [u for u in data["users"] if u["id"] not in special][:MEASURED_CALLS]

    tokens = {}
    for name, user in (("admin", admin), ("senior", senior), ("approver", data["approver"]),
                       ("escalator", data["escalator"]), ("queue", data["queue_lead"])):
        tokens[name] = client.login(user)

    def get(path, who):
        return lambda: client.call("GET", path, tokens[who])

    def detail(request_id):
        def run():
            for suffix in ("", "/approvals", "/comments", "/review-actions"):
                client.call("GET", f"/change-requests/{request_id}{suffix}", tokens["admin"])
        return run

    def user_list():
        client.call("GET", "/users/", tokens["admin"])
        client.call("GET", "/roles/", tokens["admin"])

    reads = [
        ("GET /users/me", get("/users/me", "senior")),
        ("Request list (admin, all requests)", get("/change-requests/", "admin")),
        ("Review queue (lead)", get("/change-requests/", "queue")),
        ("User list page (admin)", user_list),
        ("Audit log (admin)", get("/audit-logs/", "admin")),
    ]
    for _, fn in reads:  # warm-up, not timed
        fn()
    detail(data["detail_ids"][0])()

    results = [("Login (password + TOTP)", [timed(lambda u=u: client.login(u)) for u in login_users])]
    for name, fn in reads[:3]:
        results.append((name, [timed(fn) for _ in range(MEASURED_CALLS)]))
    results.append(("Request detail page (4 calls)", [timed(detail(rid)) for rid in data["detail_ids"]]))
    for name, fn in reads[3:]:
        results.append((name, [timed(fn) for _ in range(MEASURED_CALLS)]))

    target = by_role["senior"][1]
    results.append(("Approve", [
        timed(lambda rid=rid: client.call("POST", f"/change-requests/{rid}/approve", tokens["approver"], json={}))
        for rid in data["approve_ids"]
    ]))
    results.append(("Escalate", [
        timed(lambda rid=rid: client.call("POST", f"/change-requests/{rid}/escalate", tokens["escalator"],
                                          json={"target_reviewer_id": target["id"]}))
        for rid in data["escalate_ids"]
    ]))
    return results


# --- report ---------------------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]  # nearest rank


def environment(server_version: str, api_url: str) -> list[str]:
    def run(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5, cwd=ROOT).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    cpu, memory = platform.processor() or platform.machine(), ""
    if sys.platform == "darwin":
        cpu = run("sysctl", "-n", "machdep.cpu.brand_string") or cpu
        mem_bytes = run("sysctl", "-n", "hw.memsize")
        memory = f"{int(mem_bytes) / 2**30:.0f} GB" if mem_bytes.isdigit() else ""
    elif Path("/proc/cpuinfo").exists():
        names = [line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                 if line.startswith("model name")]
        cpu = names[0] if names else cpu
        memory = f"{os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') / 2**30:.0f} GB"

    def version(package):
        try:
            return metadata.version(package)
        except metadata.PackageNotFoundError:
            return "?"

    packages = ", ".join(f"{p} {version(p)}" for p in
                         ("fastapi", "starlette", "uvicorn", "SQLAlchemy", "psycopg", "pydantic", "httpx"))
    return [
        f"Machine:    {platform.node()} | {platform.platform()} | {cpu} | {os.cpu_count()} CPUs"
        + (f" | {memory} RAM" if memory else ""),
        f"Software:   Python {platform.python_version()} | PostgreSQL {server_version} | {packages}",
        f"Accessa:    commit {run('git', 'rev-parse', '--short', 'HEAD') or '?'} | API {api_url} "
        "| client and server on the same machine, one call at a time",
    ]


def report(results, data, slug, api_url, started) -> bool:
    print(f"\nNFR-06 response-time check — {started:%Y-%m-%d %H:%M:%S %Z}")
    for line in environment(data["server_version"], api_url):
        print(line)
    c = data["counts"]
    print(f"Workspace:  {slug} | {c['users']} users | {c['change_requests']} requests "
          f"({', '.join(f'{k} {v}' for k, v in sorted(data['status_counts'].items()))}) | "
          f"{c['approvals']} approvals | {c['comments']} comments | {c['review_actions']} review actions | "
          f"{c['audit_logs']} audit records")
    print(f"Review queue: {data['queue_size']} requests assigned to the measured lead\n")

    header = f"{'Endpoint':<38} {'Calls':>5} {'Median':>9} {'p95':>9} {'Max':>9}  Result"
    print(header)
    print("-" * len(header))
    all_pass = True
    for name, values in results:
        p95, worst = percentile(values, 95), max(values)
        ok = worst < LIMIT_MS
        all_pass &= ok
        print(f"{name:<38} {len(values):>5} {statistics.median(values):>9.1f} {p95:>9.1f} {worst:>9.1f}  "
              f"{'PASS' if ok else 'FAIL'}")
    print(f"\nTimes in ms. PASS: every call (maximum) under {LIMIT_MS} ms.")
    print(f"NFR-06 overall: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", type=int, default=6, help="random seed for the generated data")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")  # explicitly set environment variables take precedence
    check_local(args.api_url)

    started = datetime.now().astimezone()
    slug = f"perf-{started:%Y%m%d-%H%M%S}"
    client = Client(args.api_url, slug, "")
    try:
        client.call("GET", "/health")
    except httpx.HTTPError as exc:
        raise SystemExit(f"FAILED: backend not reachable at {args.api_url} ({exc.__class__.__name__}). Start uvicorn first.")

    print(f"Creating workspace '{slug}' ...")
    t0 = time.perf_counter()
    data = build_workspace(random.Random(args.seed), slug)
    client.password = data.pop("password")
    print(f"  done in {time.perf_counter() - t0:.1f}s; measuring ...")

    results = measure(client, data)
    sys.exit(0 if report(results, data, slug, args.api_url, started) else 1)


if __name__ == "__main__":
    main()
