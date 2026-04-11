import client from "./client";

export async function getUsers() {
  const response = await client.get("/users/");
  return response.data;
}

export async function getRoles() {
  const response = await client.get("/roles/");
  return response.data;
}

export async function getReviewers(requesterRole, riskLevel) {
  const params = {};
  if (requesterRole) params.requester_role = requesterRole;
  if (riskLevel) params.risk_level = riskLevel;
  const response = await client.get("/users/reviewers", { params });
  return response.data;
}

export async function getMe() {
  const response = await client.get("/users/me");
  return response.data;
}

export async function createUser(payload) {
  const response = await client.post("/users/", payload);
  return response.data;
}

export async function updateUserRole(userId, roleId) {
  const response = await client.patch(`/users/${userId}/role`, {
    role_id: roleId,
  });
  return response.data;
}

export async function deactivateUser(userId) {
  const response = await client.patch(`/users/${userId}/deactivate`);
  return response.data;
}

export async function reactivateUser(userId) {
  const response = await client.patch(`/users/${userId}/reactivate`);
  return response.data;
}

export async function getUserDetails(userId) {
  const response = await client.get(`/users/${userId}/details`);
  return response.data;
}