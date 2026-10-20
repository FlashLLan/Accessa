const APPROVAL_MATRIX = {
  "junior,low":    ["mid", "senior", "lead"],
  "junior,medium": ["senior", "lead"],
  "junior,high":   ["senior", "lead"],
  "mid,low":       ["senior", "lead"],
  "mid,medium":    ["senior", "lead"],
  "mid,high":      ["senior", "lead"],
  "senior,low":    ["senior", "lead"],
  "senior,medium": ["senior", "lead"],
  "senior,high":   ["lead"],
  "lead,low":      ["lead"],
  "lead,medium":   ["lead"],
  "lead,high":     ["lead"],
  "admin,low":     ["admin"],
  "admin,medium":  ["admin"],
  "admin,high":    ["admin"],
};

function getAllowedApproverRoles(requesterRole, riskLevel) {
  return APPROVAL_MATRIX[`${requesterRole},${riskLevel}`] || [];
}

export function isRequestCreator(user, request) {
  if (!user?.email || !request?.creator?.email) return false;
  return user.email.toLowerCase() === request.creator.email.toLowerCase();
}

export function isAssignedReviewer(user, request) {
  if (!user?.email || !request?.assigned_reviewer?.email) return false;
  return (
    user.email.toLowerCase() === request.assigned_reviewer.email.toLowerCase()
  );
}

export function isCurrentReviewer(user, request) {
  if (request?.current_reviewer) {
    if (!user?.email) return false;
    return user.email.toLowerCase() === request.current_reviewer.email.toLowerCase();
  }
  return isAssignedReviewer(user, request);
}

export function isAdmin(user) {
  return user?.role === "admin";
}

export function canSubmitRequest(user, request) {
  return (
    isRequestCreator(user, request) &&
    request?.status === "draft"
  );
}

export function canReviewRequest(user, request) {
  if (request?.status !== "pending_review") return false;
  if (isRequestCreator(user, request)) return false;

  // If escalated/delegated to a specific reviewer, only they can act
  if (request?.current_reviewer) {
    return isCurrentReviewer(user, request);
  }

  const requesterRole = request?.creator?.role?.name;
  const riskLevel = request?.risk_level;
  const userRole = user?.role;

  if (!requesterRole || !riskLevel || !userRole) return false;

  return getAllowedApproverRoles(requesterRole, riskLevel).includes(userRole);
}

export function canApproveRequest(user, request) {
  return canReviewRequest(user, request);
}

export function canRejectRequest(user, request) {
  return canReviewRequest(user, request);
}

export function canApplyRequest(user, request) {
  return request?.status === "approved" && (
    isRequestCreator(user, request) || isAdmin(user)
  );
}

export function canViewRequestComments(user, request) {
  return (
    isAdmin(user) ||
    isRequestCreator(user, request) ||
    isAssignedReviewer(user, request)
  );
}

export function canEscalateRequest(user, request) {
  if (request?.status !== "pending_review") return false;
  if (isRequestCreator(user, request)) return false;
  return isAdmin(user) || isCurrentReviewer(user, request);
}

export function canDelegateRequest(user, request) {
  if (request?.status !== "pending_review") return false;
  if (isRequestCreator(user, request)) return false;
  return isAdmin(user) || isCurrentReviewer(user, request);
}