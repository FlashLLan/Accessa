import client from "./client";

export async function loginRequest({ workspaceSlug, email, password }) {
  const response = await client.post("/auth/login", {
    workspace_slug: workspaceSlug,
    email,
    password,
  });

  return response.data;
}

export async function signupRequest({ workspaceName, workspaceSlug, fullName, email, password }) {
  const response = await client.post("/auth/signup", {
    workspace_name: workspaceName,
    workspace_slug: workspaceSlug,
    full_name: fullName,
    email,
    password,
  });

  return response.data;
}

// Second login step. Sends the short-lived mfa_pending token from the login
// response (never stored), not the access token.
export async function verifyMfaRequest(mfaToken, code) {
  const response = await client.post(
    "/auth/mfa/verify",
    { code },
    { headers: { Authorization: `Bearer ${mfaToken}` } }
  );
  return response.data;
}

// Enrolment while logged in (first login: after the password change).
export async function setupMfa() {
  const response = await client.post("/auth/mfa/setup");
  return response.data;
}

export async function confirmMfa(code) {
  const response = await client.post("/auth/mfa/confirm", { code });
  return response.data;
}
