import client from "./client";

export async function getChangeRequests() {
  const response = await client.get("/change-requests/");
  return response.data;
}

export async function getChangeRequestById(id) {
  const response = await client.get(`/change-requests/${id}`);
  return response.data;
}

export async function createChangeRequest(payload) {
  const response = await client.post("/change-requests/", payload);
  return response.data;
}

export async function submitChangeRequest(id) {
  const response = await client.post(`/change-requests/${id}/submit`);
  return response.data;
}

export async function approveChangeRequest(id, decision_comment = "") {
  const response = await client.post(`/change-requests/${id}/approve`, {
    decision_comment,
  });
  return response.data;
}

export async function rejectChangeRequest(id, decision_comment = "") {
  const response = await client.post(`/change-requests/${id}/reject`, {
    decision_comment,
  });
  return response.data;
}

export async function getChangeRequestApprovals(id) {
  const response = await client.get(`/change-requests/${id}/approvals`);
  return response.data;
}

export async function getChangeRequestComments(id) {
  const response = await client.get(`/change-requests/${id}/comments`);
  return response.data;
}

export async function addChangeRequestComment(id, comment_text) {
  const response = await client.post(`/change-requests/${id}/comments`, {
    comment_text,
  });
  return response.data;
}

export async function applyChangeRequest(id) {
  const response = await client.post(`/change-requests/${id}/apply`);
  return response.data;
}

export async function escalateChangeRequest(id, target_reviewer_id, comment = "") {
  const response = await client.post(`/change-requests/${id}/escalate`, {
    target_reviewer_id,
    comment: comment || null,
  });
  return response.data;
}

export async function delegateChangeRequest(id, target_reviewer_id, comment = "") {
  const response = await client.post(`/change-requests/${id}/delegate`, {
    target_reviewer_id,
    comment: comment || null,
  });
  return response.data;
}

export async function getReviewActions(id) {
  const response = await client.get(`/change-requests/${id}/review-actions`);
  return response.data;
}
export async function getAiReviews(id) {
  const response = await client.get(`/change-requests/${id}/ai-review`);
  return response.data;
}

// scope: "changed_files" (default) or "extended", chosen by the reviewer.
// force: generate even if the commit and scope equal the latest result's (the
// backend otherwise answers 409 with code "ai_review_unchanged").
export async function generateAiReview(id, scope = "changed_files", force = false) {
  const response = await client.post(`/change-requests/${id}/ai-review`, { scope, force });
  return response.data;
}
