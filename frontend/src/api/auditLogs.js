import client from "./client";

export async function getAuditLogs() {
  const res = await client.get("/audit-logs/");
  return res.data;
}
