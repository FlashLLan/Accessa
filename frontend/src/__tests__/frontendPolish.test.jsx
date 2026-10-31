// One date format, capitalised roles, the header and the review queue cards.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const auth = vi.hoisted(() => ({ user: null }));
const list = vi.hoisted(() => vi.fn());

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: auth.user, logout: vi.fn(), refreshMe: vi.fn() }),
}));
vi.mock("../services/requestsService.js", () => ({
  requestService: { list, approve: vi.fn(), reject: vi.fn() },
}));

const { formatDateTime } = await import("../utils/requestPresentation");
const { formatRole } = await import("../utils/roleUtils");
const { default: Topbar } = await import("../components/layout/Topbar");
const { default: Sidebar } = await import("../components/layout/Sidebar");
const { default: ReviewPage } = await import("../pages/ReviewPage");

afterEach(cleanup);

describe("formatDateTime", () => {
  // Server timestamps are UTC without a zone marker; shown in local time.
  const local = new Date(2026, 9, 31, 16, 8, 5);
  const utc = local.toISOString().slice(0, 19);

  it("shows day/month/year and 24-hour time", () => {
    expect(formatDateTime(utc)).toBe("31/10/2026 16:08");
  });

  it("adds seconds only when asked (audit log)", () => {
    expect(formatDateTime(utc, { seconds: true })).toBe("31/10/2026 16:08:05");
  });

  it("shows a dash for a missing or invalid value", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("not a date")).toBe("—");
  });
});

describe("formatRole", () => {
  it.each([["junior", "Junior"], ["mid", "Mid"], ["senior", "Senior"], ["lead", "Lead"], ["admin", "Admin"]])(
    "%s -> %s", (role, label) => expect(formatRole(role)).toBe(label)
  );
});

describe("layout", () => {
  const user = { name: "Ada", role: "senior", workspace: { name: "Acme Ops", slug: "acme" }, pending_reviews_count: 0 };

  it("the header shows the workspace name and the capitalised role", () => {
    auth.user = user;
    render(<MemoryRouter><Topbar /></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Acme Ops");
    expect(screen.getByText("Workspace")).toBeTruthy();
    expect(screen.getByText("Senior")).toBeTruthy();
    expect(screen.queryByText("Welcome back")).toBeNull();
  });

  it("the sidebar has no role box", () => {
    auth.user = user;
    render(<MemoryRouter><Sidebar /></MemoryRouter>);
    expect(screen.queryByText("Current role")).toBeNull();
  });
});

describe("review queue card", () => {
  it("only opens the request: no decision buttons or comment box", async () => {
    auth.user = { id: 2, email: "rev@example.com", role: "senior" };
    list.mockResolvedValue([{
      id: 7, title: "Rotate keys", description: "d", status: "pending_review", risk_level: "high",
      request_type: "access_change", created_at: "2026-10-31T10:00:00",
      creator: { id: 1, full_name: "Junior Dev", role: { name: "junior" } },
      assigned_reviewer: { id: 2, email: "rev@example.com" },
    }]);
    render(<MemoryRouter><ReviewPage /></MemoryRouter>);

    const open = await screen.findByRole("link", { name: "Open" });
    expect(open.getAttribute("href")).toBe("/requests/7");
    expect(open.className).toContain("btn-primary");
    expect(screen.getByText("Junior Dev", { exact: false })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /approve|reject/i })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
