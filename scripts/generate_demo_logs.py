"""
Demo data generation script — creates users, change requests, and review actions
to produce meaningful audit log entries for the project defence.
"""
import requests

BASE = "http://localhost:8000"


def login(email, password):
    r = requests.post(f"{BASE}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()["access_token"]


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def get_roles(token):
    r = requests.get(f"{BASE}/roles/", headers=headers(token))
    r.raise_for_status()
    return {role["name"]: role["id"] for role in r.json()}


def get_user_by_email(token, email):
    r = requests.get(f"{BASE}/users/", headers=headers(token), params={"search": email})
    r.raise_for_status()
    for u in r.json():
        if u["email"] == email:
            return u
    return None


def create_user(token, full_name, email, password, role_id):
    existing = get_user_by_email(token, email)
    if existing:
        print(f"  User {email} already exists (id={existing['id']}), skipping creation.")
        return existing
    r = requests.post(f"{BASE}/users/", headers=headers(token), json={
        "full_name": full_name,
        "email": email,
        "password": password,
        "role_id": role_id,
    })
    r.raise_for_status()
    return r.json()


def deactivate_user(token, user_id):
    r = requests.patch(f"{BASE}/users/{user_id}/deactivate", headers=headers(token))
    if r.status_code == 400 and "already inactive" in r.text:
        print(f"  User {user_id} already inactive, skipping.")
        return
    r.raise_for_status()
    return r.json()


def create_request(token, title, description, request_type, target_system,
                   environment, risk_level, reviewer_id):
    r = requests.post(f"{BASE}/change-requests/", headers=headers(token), json={
        "title": title,
        "description": description,
        "request_type": request_type,
        "target_system": target_system,
        "environment": environment,
        "risk_level": risk_level,
        "assigned_reviewer_id": reviewer_id,
    })
    r.raise_for_status()
    return r.json()


def submit_request(token, request_id):
    r = requests.post(f"{BASE}/change-requests/{request_id}/submit", headers=headers(token))
    r.raise_for_status()
    return r.json()


def approve_request(token, request_id, comment="Looks good, approved."):
    r = requests.post(f"{BASE}/change-requests/{request_id}/approve",
                      headers=headers(token),
                      json={"decision_comment": comment})
    r.raise_for_status()
    return r.json()


def reject_request(token, request_id, comment="Does not meet standards."):
    r = requests.post(f"{BASE}/change-requests/{request_id}/reject",
                      headers=headers(token),
                      json={"decision_comment": comment})
    r.raise_for_status()
    return r.json()


def escalate_request(token, request_id, target_id, comment=None):
    r = requests.post(f"{BASE}/change-requests/{request_id}/escalate",
                      headers=headers(token),
                      json={"target_reviewer_id": target_id, "comment": comment})
    r.raise_for_status()
    return r.json()


def delegate_request(token, request_id, target_id, comment=None):
    r = requests.post(f"{BASE}/change-requests/{request_id}/delegate",
                      headers=headers(token),
                      json={"target_reviewer_id": target_id, "comment": comment})
    r.raise_for_status()
    return r.json()


def add_comment(token, request_id, text):
    r = requests.post(f"{BASE}/change-requests/{request_id}/comments",
                      headers=headers(token),
                      json={"comment_text": text})
    r.raise_for_status()
    return r.json()


def apply_request(token, request_id):
    r = requests.post(f"{BASE}/change-requests/{request_id}/apply", headers=headers(token))
    r.raise_for_status()
    return r.json()


def change_password(token, current_pw, new_pw):
    r = requests.put(f"{BASE}/users/me/password", headers=headers(token), json={
        "current_password": current_pw,
        "new_password": new_pw,
        "confirm_password": new_pw,
    })
    r.raise_for_status()


# ── Main ────────────────────────────────────────────────────────────────────

print("=== Logging in as admin ===")
admin_token = login("admin@test.com", "123456")

print("=== Fetching roles ===")
roles = get_roles(admin_token)
print("Roles:", roles)

# ── Create users ────────────────────────────────────────────────────────────

print("\n=== Creating users ===")
junior = create_user(admin_token, "Alice Junior", "alice@demo.com", "Password1!", roles["junior"])
mid    = create_user(admin_token, "Bob Mid",      "bob@demo.com",   "Password1!", roles["mid"])
senior = create_user(admin_token, "Carol Senior", "carol@demo.com", "Password1!", roles["senior"])
lead   = create_user(admin_token, "David Lead",   "david@demo.com", "Password1!", roles["lead"])

# Two users to deactivate immediately
temp1 = create_user(admin_token, "Eve Temp",   "eve@demo.com",  "Password1!", roles["junior"])
temp2 = create_user(admin_token, "Frank Temp", "frank@demo.com","Password1!", roles["mid"])

print(f"Created: alice(id={junior['id']}), bob(id={mid['id']}), carol(id={senior['id']}), david(id={lead['id']})")
print(f"Temp users: eve(id={temp1['id']}), frank(id={temp2['id']})")

print("\n=== Deactivating temp users ===")
deactivate_user(admin_token, temp1["id"])
print(f"Deactivated eve(id={temp1['id']})")
deactivate_user(admin_token, temp2["id"])
print(f"Deactivated frank(id={temp2['id']})")

# ── Login as created users ───────────────────────────────────────────────────

alice_token = login("alice@demo.com", "Password1!")
bob_token   = login("bob@demo.com",   "Password1!")
carol_token = login("carol@demo.com", "Password1!")
david_token = login("david@demo.com", "Password1!")

# ── Scenario 1: junior creates request -> mid approves ───────────────────────

print("\n=== Scenario 1: Create + Approve ===")
cr1 = create_request(alice_token,
    title="Add read access to production DB",
    description="Need read-only access to query production database for debugging purposes.",
    request_type="access_change",
    target_system="PostgreSQL Production",
    environment="production",
    risk_level="low",
    reviewer_id=mid["id"],
)
submit_request(alice_token, cr1["id"])
add_comment(bob_token, cr1["id"], "I reviewed the access scope, looks minimal and justified.")
approve_request(bob_token, cr1["id"], "Access is read-only and scoped correctly. Approved.")
apply_request(alice_token, cr1["id"])
print(f"CR1 (id={cr1['id']}): created by alice -> approved by bob -> applied")

# ── Scenario 2: junior creates request (high risk) -> senior rejects ──────────
# junior+high requires senior or lead reviewer

print("\n=== Scenario 2: Create + Reject ===")
cr2 = create_request(alice_token,
    title="Deploy hotfix to production",
    description="Deploy unreviewed hotfix directly to production environment.",
    request_type="deployment_change",
    target_system="Production Server",
    environment="production",
    risk_level="high",
    reviewer_id=senior["id"],
)
submit_request(alice_token, cr2["id"])
add_comment(carol_token, cr2["id"], "This bypasses the staging process entirely.")
reject_request(carol_token, cr2["id"], "Hotfix must go through staging first. Process not followed.")
print(f"CR2 (id={cr2['id']}): created by alice -> rejected by carol")

# ── Scenario 3: junior creates request (medium risk) -> senior delegates to another senior ──
# junior+medium requires senior or lead; senior can delegate to another senior

print("\n=== Scenario 3: Create + Delegate ===")
henry = create_user(admin_token, "Henry Senior", "henry@demo.com", "Password1!", roles["senior"])
henry_token = login("henry@demo.com", "Password1!")

cr3 = create_request(alice_token,
    title="Update firewall rules",
    description="Add inbound rule to allow traffic on port 8443.",
    request_type="configuration_change",
    target_system="Firewall",
    environment="staging",
    risk_level="medium",
    reviewer_id=senior["id"],
)
submit_request(alice_token, cr3["id"])
add_comment(carol_token, cr3["id"], "I have a conflict of interest — delegating to Henry.")
delegate_request(carol_token, cr3["id"], henry["id"], "Delegating due to conflict of interest.")
add_comment(henry_token, cr3["id"], "Reviewed firewall rules. Change is within policy.")
approve_request(henry_token, cr3["id"], "Approved after independent review.")
print(f"CR3 (id={cr3['id']}): created by alice -> delegated by carol -> approved by henry")

# ── Scenario 4: mid creates request -> senior escalates to lead ──────────────

print("\n=== Scenario 4: Create + Escalate ===")
cr4 = create_request(bob_token,
    title="Migrate authentication service",
    description="Replace legacy auth with OAuth2.0 provider. High security impact.",
    request_type="security_change",
    target_system="Auth Service",
    environment="production",
    risk_level="high",
    reviewer_id=senior["id"],
)
submit_request(bob_token, cr4["id"])
add_comment(carol_token, cr4["id"], "This exceeds my authority level. Escalating to lead.")
escalate_request(carol_token, cr4["id"], lead["id"],
                 "Security impact requires lead-level sign-off.")
add_comment(david_token, cr4["id"], "Reviewed architecture. OAuth2 migration plan is solid.")
approve_request(david_token, cr4["id"], "Approved at lead level. Migration plan is sound.")
apply_request(bob_token, cr4["id"])
print(f"CR4 (id={cr4['id']}): created by bob -> escalated by carol -> approved by david -> applied")

# ── Scenario 5: senior creates request -> rejected ───────────────────────────

print("\n=== Scenario 5: Senior request -> Rejected ===")
cr5 = create_request(carol_token,
    title="Grant admin access to CI pipeline",
    description="CI system needs admin-level DB access to run migration scripts.",
    request_type="administrative_change",
    target_system="CI/CD Pipeline",
    environment="production",
    risk_level="high",
    reviewer_id=lead["id"],
)
submit_request(carol_token, cr5["id"])
add_comment(david_token, cr5["id"], "Admin DB access for CI is too broad. Use a scoped service account.")
reject_request(david_token, cr5["id"], "Scope is too wide. Resubmit with least-privilege approach.")
print(f"CR5 (id={cr5['id']}): created by carol -> rejected by david")

# ── Scenario 6: Alice changes her password ──────────────────────────────────

print("\n=== Scenario 6: Password change ===")
change_password(alice_token, "Password1!", "NewPassword2!")
print("Alice changed her password")

print("\n=== All done! Check the audit logs in the admin panel. ===")
