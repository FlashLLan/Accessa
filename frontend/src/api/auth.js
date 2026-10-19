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
