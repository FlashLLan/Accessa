import client from "./client";

export async function getWorkspaceSettings() {
  const response = await client.get("/workspace/settings");
  return response.data;
}

export async function updateWorkspaceSettings(data) {
  const response = await client.patch("/workspace/settings", data);
  return response.data;
}
