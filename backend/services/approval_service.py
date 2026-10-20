from backend.models.change_request import ChangeRequest
from backend.models.enums import RequestStatus
from backend.models.user import User

APPROVAL_MATRIX = {
    ("junior", "low"):    ["mid", "senior", "lead"],
    ("junior", "medium"): ["senior", "lead"],
    ("junior", "high"):   ["senior", "lead"],

    ("mid", "low"):    ["senior", "lead"],
    ("mid", "medium"): ["senior", "lead"],
    ("mid", "high"):   ["senior", "lead"],

    ("senior", "low"):    ["senior", "lead"],
    ("senior", "medium"): ["senior", "lead"],
    ("senior", "high"):   ["lead"],

    ("lead", "low"):    ["lead"],
    ("lead", "medium"): ["lead"],
    ("lead", "high"):   ["lead"],

    ("admin", "low"):    ["admin"],
    ("admin", "medium"): ["admin"],
    ("admin", "high"):   ["admin"],
}


def get_allowed_approver_roles(requester_role: str, severity: str) -> list[str]:
    return APPROVAL_MATRIX.get((requester_role, severity), [])


def can_user_decide_request(
    approver: User,
    request_obj: ChangeRequest,
    active_admin_count: int | None = None,
) -> tuple[bool, str]:
    """
    Returns (allowed, reason_code).

    reason_code values:
      ""                          - allowed
      "not_pending"               - request is not in pending_review state
      "self_approval"             - approver is the requester
      "invalid_matrix_key"        - unsupported requester role / severity combination
      "unauthorized_role"         - approver role not in the matrix for this request
      "not_assigned_reviewer"     - approver is not the request's assigned reviewer
      "admin_insufficient_admins" - admin workflow requires >= 2 active admins

    Evaluation order per spec:
      1. request status is pending_review
      2. approver is not the requester
      3. requester role + severity exist in the matrix
      4. approver role is in the allowed set
      5. approver must be the assigned reviewer (escalation and delegation move
         assigned_reviewer_id to the new reviewer, so this also covers transfers)
      6. if requester is admin, active_admin_count >= 2
    """
    if request_obj.status != RequestStatus.PENDING_REVIEW:
        return False, "not_pending"

    if approver.id == request_obj.created_by:
        return False, "self_approval"

    requester_role = request_obj.creator.role.name
    severity = request_obj.risk_level.value

    allowed_roles = get_allowed_approver_roles(requester_role, severity)
    if not allowed_roles:
        return False, "invalid_matrix_key"

    if approver.role.name not in allowed_roles:
        return False, "unauthorized_role"

    if approver.id != request_obj.assigned_reviewer_id:
        return False, "not_assigned_reviewer"

    if requester_role == "admin":
        if active_admin_count is None or active_admin_count < 2:
            return False, "admin_insufficient_admins"

    return True, ""
