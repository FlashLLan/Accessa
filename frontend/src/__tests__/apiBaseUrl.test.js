// Production serves the API under https://<domain>/api (Caddy strips /api).
// Every API call must stay under that base URL: relative paths only.
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import client from "../api/client";
import * as auth from "../api/auth";
import * as changeRequests from "../api/changeRequests";
import * as users from "../api/users";
import * as auditLogs from "../api/auditLogs";

const BASE = "https://accessa.example.org/api";
const seen = [];
let original;

beforeAll(() => {
  original = { baseURL: client.defaults.baseURL, adapter: client.defaults.adapter };
  client.defaults.baseURL = BASE;
  client.defaults.adapter = async (config) => {
    seen.push(client.getUri(config));
    return { data: [], status: 200, statusText: "OK", headers: {}, config };
  };
});

afterAll(() => {
  Object.assign(client.defaults, original);
});

describe("API base URL with a path", () => {
  it("keeps every API call under /api", async () => {
    const calls = [
      () => auth.loginRequest({ workspaceSlug: "demo", email: "a@b.c", password: "x" }),
      () => auth.verifyMfaRequest("pending-token", "123456"),
      () => auth.setupMfa(),
      () => changeRequests.getChangeRequests(),
      () => changeRequests.getChangeRequestById(7),
      () => changeRequests.getAiReviews(7),
      () => changeRequests.generateAiReview(7, "extended", true),
      () => changeRequests.getGitHead(7),
      () => users.getMe(),
      () => users.resetUserMfa(4),
      () => auditLogs.getAuditLogs(),
    ];
    for (const call of calls) await call();

    expect(seen).toHaveLength(calls.length);
    for (const url of seen) {
      expect(url.startsWith(`${BASE}/`)).toBe(true);
    }
    expect(seen).toContain(`${BASE}/auth/login`);
    expect(seen).toContain(`${BASE}/change-requests/7/ai-review`);
    expect(seen).toContain(`${BASE}/users/4/mfa-reset`);
  });
});
