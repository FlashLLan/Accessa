// Escalate and delegate: only the assigned reviewer of a pending request, never
// the creator. An admin who is not assigned gets no exception (same rule as the backend).
import { describe, expect, it } from "vitest";
import { canDelegateRequest, canEscalateRequest } from "../utils/requestPermissions";

const person = (email, role) => ({ email, role, full_name: email });

const CREATOR = person("creator@test.com", "admin");
const REVIEWER = person("reviewer@test.com", "admin");
const OTHER_ADMIN = person("other@test.com", "admin");

const request = (status = "pending_review") => ({
  status,
  risk_level: "low",
  creator: { email: CREATOR.email, role: { name: "admin" } },
  assigned_reviewer: { email: REVIEWER.email },
});

describe.each([
  ["canEscalateRequest", canEscalateRequest],
  ["canDelegateRequest", canDelegateRequest],
])("%s", (_name, can) => {
  it("allows the assigned reviewer", () => {
    expect(can(REVIEWER, request())).toBe(true);
  });

  it("refuses an admin who is not the assigned reviewer", () => {
    expect(can(OTHER_ADMIN, request())).toBe(false);
  });

  it("refuses the creator", () => {
    expect(can(CREATOR, request())).toBe(false);
  });

  it.each(["draft", "approved", "rejected", "applied"])("refuses a %s request", (status) => {
    expect(can(REVIEWER, request(status))).toBe(false);
  });
});
