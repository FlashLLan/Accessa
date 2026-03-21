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

export function isAdmin(user) {
  return user?.role === "admin";
}

export function canSubmitRequest(user, request) {
  return (
    isRequestCreator(user, request) &&
    (request?.status === "draft" || request?.status === "rejected")
  );
}

export function canReviewRequest(user, request) {
  return (
    request?.status === "pending_review" &&
    !isRequestCreator(user, request) &&
    (isAdmin(user) || isAssignedReviewer(user, request))
  );
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