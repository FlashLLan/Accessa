// The workspace's sign-in link (https://<current host>/w/<slug>) on User
// Management (with Copy and in the "user created" message) and on the Account page.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const ADMIN = {
  id: 1, full_name: "Alice Admin", email: "admin@test.com", role: "admin", is_active: true,
  created_at: "2026-10-20T10:00:00", workspace: { name: "Acme Ops", slug: "acme-ops", public_id: "b1c2" },
};

const api = vi.hoisted(() => ({
  getUsers: vi.fn(async () => []),
  getRoles: vi.fn(async () => [{ id: 1, name: "junior" }]),
  createUser: vi.fn(async () => ({ id: 2 })),
  getUserDetails: vi.fn(), updateUserRole: vi.fn(), deactivateUser: vi.fn(), reactivateUser: vi.fn(),
  resetUserMfa: vi.fn(),
  getMyStats: vi.fn(async () => ({})), updateMe: vi.fn(), changePassword: vi.fn(),
}));
vi.mock("../api/users", () => api);
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: ADMIN, refreshMe: vi.fn() }) }));

const { default: UserManagementPage } = await import("../pages/UserManagementPage");
const { default: AccountPage } = await import("../pages/AccountPage");
const { workspaceSignInUrl } = await import("../utils/storage");

const LINK = `${window.location.origin}/w/acme-ops`;

let clipboard;
beforeEach(() => {
  clipboard = { writeText: vi.fn(async () => {}) };
  Object.defineProperty(navigator, "clipboard", { value: clipboard, configurable: true });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPage(page) {
  render(<MemoryRouter>{page}</MemoryRouter>);
}

describe("workspaceSignInUrl", () => {
  it("is the current host plus /w/<slug>", () => {
    expect(workspaceSignInUrl("acme-ops")).toBe(LINK);
    expect(workspaceSignInUrl("")).toBe("");
  });
});

describe("User Management", () => {
  it("shows the current workspace's sign-in link and copies it", async () => {
    renderPage(<UserManagementPage />);
    const link = await screen.findByText(LINK);
    expect(link.textContent).toContain("/w/acme-ops");

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(clipboard.writeText).toHaveBeenCalledWith(LINK);
  });

  it("puts the link into the message after a user is created", async () => {
    renderPage(<UserManagementPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Add User" }));
    fireEvent.change(screen.getByLabelText(/Full name/i), { target: { value: "Jun Dev" } });
    fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "jun@test.com" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "initial-pass-1" } });
    await waitFor(() => expect(screen.getAllByRole("option", { name: /Junior/ }).length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText(/Role/i), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /Create User/i }));

    const message = await screen.findByRole("alert");
    expect(message.textContent).toContain(`sign-in link ${LINK}`);
    expect(message.textContent).toContain("initial password");
  });
});

describe("Account page", () => {
  it("shows the current workspace's sign-in link", async () => {
    renderPage(<AccountPage />);
    expect((await screen.findByText(LINK)).textContent).toBe(`${window.location.origin}/w/acme-ops`);
  });
});
