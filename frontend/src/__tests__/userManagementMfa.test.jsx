// User Management: MFA status, Reset MFA with toast messages, expandable Details row.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const api = vi.hoisted(() => ({
  getUsers: vi.fn(),
  getRoles: vi.fn(async () => [{ id: 3, name: "senior" }, { id: 5, name: "admin" }]),
  resetUserMfa: vi.fn(),
  getUserDetails: vi.fn(),
  createUser: vi.fn(), updateUserRole: vi.fn(), deactivateUser: vi.fn(), reactivateUser: vi.fn(),
}));

vi.mock("../api/users", () => api);
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: { id: 1, role: "admin", email: "admin@test.com" } }) }));

const { default: UserManagementPage } = await import("../pages/UserManagementPage");

const ADMIN = { id: 1, full_name: "Alice Admin", email: "admin@test.com", role: { id: 5, name: "admin" },
                is_active: true, mfa_enabled: true, created_at: "2026-10-20T10:00:00" };
const SAM = { id: 4, full_name: "Sam Senior", email: "senior@test.com", role: { id: 3, name: "senior" },
              is_active: true, mfa_enabled: true, created_at: "2026-10-20T10:00:00" };
const SOFIA = { ...SAM, id: 5, full_name: "Sofia Senior", email: "senior2@test.com", mfa_enabled: false };

beforeEach(() => {
  api.getUsers.mockResolvedValue([ADMIN, SAM, SOFIA]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function row(name) {
  return (await screen.findByText(name)).closest("tr");
}

function renderPage() {
  render(<MemoryRouter><UserManagementPage /></MemoryRouter>);
}

describe("MFA in User Management", () => {
  it("shows each user's real MFA status", async () => {
    renderPage();
    expect(within(await row("Sam Senior")).getByText("MFA enrolled")).toBeTruthy();
    expect(within(await row("Sofia Senior")).getByText("MFA not set up")).toBeTruthy();
  });

  it("Reset MFA is enabled for an enrolled user, disabled otherwise, absent for yourself", async () => {
    renderPage();
    expect(within(await row("Sam Senior")).getByRole("button", { name: "Reset MFA" }).disabled).toBe(false);
    expect(within(await row("Sofia Senior")).getByRole("button", { name: "Reset MFA" }).disabled).toBe(true);
    expect(within(await row("Alice Admin")).queryByRole("button", { name: "Reset MFA" })).toBeNull();
  });

  it("resets after confirmation and shows a success message", async () => {
    api.resetUserMfa.mockResolvedValue({ ...SAM, mfa_enabled: false });
    renderPage();
    fireEvent.click(within(await row("Sam Senior")).getByRole("button", { name: "Reset MFA" }));

    const dialog = (await screen.findByText("Reset two-factor authentication")).closest(".confirm-modal");
    api.getUsers.mockResolvedValue([ADMIN, { ...SAM, mfa_enabled: false }, SOFIA]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset MFA" }));

    await waitFor(() => expect(api.resetUserMfa).toHaveBeenCalledWith(4));
    const toast = await screen.findByRole("alert");
    expect(toast.className).toContain("toast-success");
    expect(toast.textContent).toContain("MFA reset for Sam Senior.");
    expect(within(await row("Sam Senior")).getByText("MFA not set up")).toBeTruthy();
  });

  it("shows the backend's error message when the reset fails", async () => {
    api.resetUserMfa.mockRejectedValue({ response: { status: 400, data: { detail: "You cannot reset your own MFA" } } });
    renderPage();
    fireEvent.click(within(await row("Sam Senior")).getByRole("button", { name: "Reset MFA" }));
    const dialog = (await screen.findByText("Reset two-factor authentication")).closest(".confirm-modal");
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset MFA" }));

    const toast = await screen.findByRole("alert");
    expect(toast.className).toContain("toast-error");
    expect(toast.textContent).toContain("You cannot reset your own MFA");
  });

  it("Details expands a row under the user, scrolls it into view, and hides it again", async () => {
    const scroll = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scroll;
    api.getUserDetails.mockResolvedValue({ ...SAM, stats: {} });
    renderPage();
    const samRow = await row("Sam Senior");
    fireEvent.click(within(samRow).getByRole("button", { name: "Details" }));

    // The details row comes directly after Sam's row.
    const toggle = await within(samRow).findByRole("button", { name: "Hide details" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const detailsRow = samRow.nextElementSibling;
    expect(detailsRow.className).toBe("user-details-row");
    expect(toggle.getAttribute("aria-controls")).toBe(detailsRow.id);
    expect(within(detailsRow).getByText("MFA").nextSibling.textContent).toBe("Enrolled");
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(scroll.mock.contexts.at(-1)).toBe(detailsRow);

    fireEvent.click(toggle);
    expect(within(samRow).getByRole("button", { name: "Details" }).getAttribute("aria-expanded")).toBe("false");
    expect(document.querySelector(".user-details-row")).toBeNull();
    expect(api.getUserDetails).toHaveBeenCalledTimes(1);
  });

  it("opening another user's details closes the first", async () => {
    api.getUserDetails.mockImplementation(async (id) => ({ ...(id === 4 ? SAM : SOFIA), stats: {} }));
    renderPage();
    fireEvent.click(within(await row("Sam Senior")).getByRole("button", { name: "Details" }));
    await within(await row("Sam Senior")).findByRole("button", { name: "Hide details" });
    fireEvent.click(within(await row("Sofia Senior")).getByRole("button", { name: "Details" }));

    await within(await row("Sofia Senior")).findByRole("button", { name: "Hide details" });
    expect(document.querySelectorAll(".user-details-row")).toHaveLength(1);
    expect((await row("Sofia Senior")).nextElementSibling.className).toBe("user-details-row");
    expect(within(await row("Sam Senior")).getByRole("button", { name: "Details" })).toBeTruthy();
  });
});
