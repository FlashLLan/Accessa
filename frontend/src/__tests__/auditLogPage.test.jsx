// Audit log page: one load (= one "Audit Log Viewed" entry) per visit, severity
// badges and filter, short summaries of long Git values.
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const api = vi.hoisted(() => ({ getAuditLogs: vi.fn() }));
vi.mock("../api/auditLogs", () => api);

const { default: AuditLogPage } = await import("../pages/AuditLogPage");
const { summarizeDetails } = await import("../utils/auditDetails");

const SHA = "c0ffee1234567890abcdef1234567890abcdef12";
const PR = "https://github.com/octo/demo/pull/7";
const REPO = "https://github.com/octo/demo";
const GIT_DETAILS = `Git context linked: provider=github; repository_url=${REPO}; branch_name=feature/x; commit_hash=${SHA}; pull_request_url=${PR}`;

const LOGS = [
  { id: 1, action: "AUDIT_VIEWED", entity_type: "audit_log", severity: "low", details: "Admin viewed audit log (3 entries)",
    created_at: "2026-10-31T10:00:00", user: { full_name: "Ada Admin" }, actor_role: "admin" },
  { id: 2, action: "GIT_CONTEXT_LINKED", entity_type: "change_request", entity_id: 7, entity_label: "Rotate keys",
    severity: "medium", details: GIT_DETAILS, created_at: "2026-10-31T10:01:00", user: { full_name: "Jun Dev" }, actor_role: "junior" },
  { id: 3, action: "ROLE_CHANGED", entity_type: "user", entity_label: "Jun Dev", severity: "high",
    details: "Role changed from 'junior' to 'mid'", created_at: "2026-10-31T10:02:00", user: { full_name: "Ada Admin" }, actor_role: "admin" },
  { id: 4, action: "MFA_LOCKED", entity_type: "user", entity_label: "Mallory", severity: "critical",
    details: "MFA locked", created_at: "2026-10-31T10:03:00", user: { full_name: "Mallory" }, actor_role: "mid" },
];

beforeEach(() => {
  api.getAuditLogs.mockResolvedValue(LOGS);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage() {
  // StrictMode as in main.jsx: it runs mount effects twice in development.
  render(
    <StrictMode>
      <MemoryRouter>
        <AuditLogPage />
      </MemoryRouter>
    </StrictMode>
  );
}

function selectByFirstOption(label) {
  return screen.getAllByRole("combobox").find((s) => s.options[0].textContent === label);
}

describe("Audit log page", () => {
  it("loads once per visit (one Audit Log Viewed entry), also when filters change", async () => {
    renderPage();
    await screen.findByText("Rotate keys");

    fireEvent.change(selectByFirstOption("All actions"), { target: { value: "ROLE_CHANGED" } });
    fireEvent.change(selectByFirstOption("All entity types"), { target: { value: "user" } });
    fireEvent.change(selectByFirstOption("All severities"), { target: { value: "high" } });
    fireEvent.change(screen.getByPlaceholderText(/Search by user/), { target: { value: "junior" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findByText("Rotate keys");

    expect(api.getAuditLogs).toHaveBeenCalledTimes(1);
  });

  it("a new visit loads again", async () => {
    renderPage();
    await screen.findByText("Rotate keys");
    cleanup();
    renderPage();
    await screen.findByText("Rotate keys");
    expect(api.getAuditLogs).toHaveBeenCalledTimes(2);
  });

  it("colours the action badge by severity", async () => {
    renderPage();
    const badge = async (label) => (await screen.findByText(label, { selector: ".status-badge" })).className;
    expect(await badge("Audit Log Viewed")).toContain("severity-low");
    expect(await badge("Git Context Linked")).toContain("severity-medium");
    expect(await badge("Role Changed")).toContain("severity-high");
    expect(await badge("MFA Locked")).toContain("severity-critical");
  });

  it("filters by severity", async () => {
    renderPage();
    await screen.findByText("Rotate keys");
    fireEvent.change(selectByFirstOption("All severities"), { target: { value: "critical" } });
    expect(screen.getByText("1 entries")).toBeTruthy();
    expect(screen.getByText("MFA Locked", { selector: ".status-badge" })).toBeTruthy();
    expect(screen.queryByText("Rotate keys")).toBeNull();
  });

  it("shows short Git values in the row and the full text when expanded", async () => {
    renderPage();
    const row = (await screen.findByText("Rotate keys")).closest("tr");
    const cell = row.querySelector(".audit-details-cell");
    expect(cell.textContent).toContain("repository_url=octo/demo;");
    expect(cell.textContent).toContain("commit_hash=c0ffee1;");
    expect(cell.textContent).toContain("pull_request_url=octo/demo#7");
    expect(cell.textContent).not.toContain(SHA);

    fireEvent.click(row);
    const extra = row.nextElementSibling;
    expect(extra.className).toBe("audit-extra-row");
    expect(within(extra).getByText(GIT_DETAILS, { exact: false }).textContent).toContain(SHA);
  });
});

describe("summarizeDetails", () => {
  it.each([
    [`commit=${SHA} (github)`, "commit=c0ffee1 (github)"],
    [`pull_request_url=${PR}`, "pull_request_url=octo/demo#7"],
    [`pull_request_url=${PR}/files`, "pull_request_url=octo/demo#7"],
    [`repository_url=${REPO}.git; branch_name=main`, "repository_url=octo/demo; branch_name=main"],
    [`repository_url=${REPO}/`, "repository_url=octo/demo"],
    ["Role changed from 'junior' to 'mid'", "Role changed from 'junior' to 'mid'"],
    ["Comment id=12 added", "Comment id=12 added"],
  ])("%s -> %s", (input, output) => {
    expect(summarizeDetails(input)).toBe(output);
  });
});
