// Editing a draft (creator only, draft only) and the manual diff fields, which are
// shown only without a GitHub pull request link.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const auth = vi.hoisted(() => ({ user: null }));
const service = vi.hoisted(() => ({
  getById: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  saveGitContext: vi.fn(),
  listApprovals: vi.fn(async () => []),
  listComments: vi.fn(async () => []),
  listReviewActions: vi.fn(async () => []),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: auth.user, refreshMe: vi.fn() }),
}));
// One module, imported as "../api/users" (form) and "../api/users.js" (details page).
vi.mock("../api/users", () => ({
  getReviewers: vi.fn(async () => [
    { id: 2, full_name: "Sam Senior", role: { name: "senior" } },
    { id: 3, full_name: "Lena Lead", role: { name: "lead" } },
  ]),
}));
vi.mock("../api/changeRequests", () => ({
  getAiReviews: vi.fn(async () => []),
  generateAiReview: vi.fn(),
  getGitHead: vi.fn(async () => null),
}));
vi.mock("../services/requestsService.js", () => ({ requestService: service }));

const { default: CreateRequestPage } = await import("../pages/CreateRequestPage");
const { default: RequestDetailsPage } = await import("../pages/RequestDetailsPage");

const CREATOR = { id: 1, email: "junior@test.com", role: "junior" };
const OTHER = { id: 9, email: "admin@test.com", role: "admin" };
const PR = "https://github.com/octo/demo/pull/7";

const DRAFT = {
  id: 7, title: "Rotate keys", description: "Rotate the API keys", status: "draft",
  request_type: "security_change", target_system: "api-gateway", environment: "production",
  risk_level: "high", created_at: "2026-11-01T10:00:00",
  creator: { id: 1, email: "junior@test.com", role: { name: "junior" } },
  assigned_reviewer: { id: 3, email: "lead@test.com", full_name: "Lena Lead", role: { name: "lead" } },
  git_context: {
    provider: "github", repository_url: "https://github.com/octo/demo", repository_name: "demo",
    branch_name: "feature/keys", target_branch: "main", commit_hash: null, pull_request_url: null,
    changed_files_summary: "config/keys.yml", diff_text: "+rotate", source: "manual",
  },
};

beforeEach(() => {
  service.getById.mockResolvedValue(DRAFT);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderAt(path) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/requests/new" element={<CreateRequestPage />} />
        <Route path="/requests/:id" element={<RequestDetailsPage />} />
        <Route path="/requests/:id/edit" element={<CreateRequestPage />} />
      </Routes>
    </MemoryRouter>
  );
}

const field = (label) => screen.getByLabelText(label);
const change = (label, value) => fireEvent.change(field(label), { target: { value } });

describe("Edit button on the request details page", () => {
  it("is shown to the creator of a draft and links to the edit form", async () => {
    auth.user = CREATOR;
    renderAt("/requests/7");
    const edit = await screen.findByRole("link", { name: "Edit" });
    expect(edit.getAttribute("href")).toBe("/requests/7/edit");
  });

  it("is not shown to anyone else, not even an admin", async () => {
    auth.user = OTHER;
    renderAt("/requests/7");
    await screen.findByText("Rotate keys");
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
  });

  it("is gone once the request is submitted", async () => {
    auth.user = CREATOR;
    service.getById.mockResolvedValue({ ...DRAFT, status: "pending_review" });
    renderAt("/requests/7");
    await screen.findByText("Rotate keys");
    expect(screen.queryByRole("link", { name: "Edit" })).toBeNull();
  });
});

describe("Edit form", () => {
  it("is pre-filled with the draft, including the Git context", async () => {
    auth.user = CREATOR;
    renderAt("/requests/7/edit");
    expect((await screen.findByLabelText("Request Title")).value).toBe("Rotate keys");
    expect(field("Description").value).toBe("Rotate the API keys");
    expect(field("Target System").value).toBe("api-gateway");
    expect(field("Request Type").value).toBe("security_change");
    expect(field("Environment").value).toBe("production");
    expect(field("Risk Level").value).toBe("high");
    await waitFor(() => expect(field("Assigned Reviewer").value).toBe("3"));
    expect(field("Branch name").value).toBe("feature/keys");
    expect(field("Changed files").value).toBe("config/keys.yml");
    expect(field("Diff / change summary").value).toBe("+rotate");
  });

  it("saves with PATCH, then the Git context, and returns to the details page", async () => {
    auth.user = CREATOR;
    service.update.mockResolvedValue({ ...DRAFT, title: "Rotate all keys" });
    renderAt("/requests/7/edit");
    await screen.findByLabelText("Request Title");
    await waitFor(() => expect(field("Assigned Reviewer").value).toBe("3"));

    change("Request Title", "Rotate all keys");
    change("Branch name", "feature/all-keys");
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await screen.findByText("Draft saved.");
    expect(service.update).toHaveBeenCalledWith("7", {
      title: "Rotate all keys", description: "Rotate the API keys", request_type: "security_change",
      target_system: "api-gateway", environment: "production", risk_level: "high", assigned_reviewer_id: 3,
    });
    expect(service.saveGitContext).toHaveBeenCalledWith("7", expect.objectContaining({
      branch_name: "feature/all-keys", diff_text: "+rotate",
    }));
    expect(service.update.mock.invocationCallOrder[0]).toBeLessThan(service.saveGitContext.mock.invocationCallOrder[0]);
  });

  it("does not touch the Git context when it did not change", async () => {
    auth.user = CREATOR;
    service.update.mockResolvedValue(DRAFT);
    renderAt("/requests/7/edit");
    await waitFor(() => expect(field("Assigned Reviewer").value).toBe("3"));
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));
    await screen.findByText("Draft saved.");
    expect(service.saveGitContext).not.toHaveBeenCalled();
  });

  it("shows the backend's message when a change is refused and stays on the form", async () => {
    auth.user = CREATOR;
    service.update.mockRejectedValue({ response: { data: {
      detail: "Selected reviewer is not allowed to approve this request based on requester role and risk level.",
    } } });
    renderAt("/requests/7/edit");
    await waitFor(() => expect(field("Assigned Reviewer").value).toBe("3"));
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Selected reviewer is not allowed");
    expect(screen.getByRole("button", { name: "Save Changes" })).toBeTruthy();
    expect(service.saveGitContext).not.toHaveBeenCalled();
  });

  it("refuses to show the form to anyone but the creator of a draft", async () => {
    auth.user = OTHER;
    renderAt("/requests/7/edit");
    expect(await screen.findByText(/Only the creator can edit a request/)).toBeTruthy();
    expect(screen.queryByLabelText("Request Title")).toBeNull();
  });
});

describe("Manual changed files and diff", () => {
  async function openCreateForm() {
    auth.user = CREATOR;
    renderAt("/requests/new");
    fireEvent.click(await screen.findByRole("button", { name: /Git-linked context/ }));
  }

  it("are shown without a pull request link", async () => {
    await openCreateForm();
    expect(field("Changed files")).toBeTruthy();
    expect(field("Diff / change summary")).toBeTruthy();
    expect(screen.queryByText("Changed files and diff will be fetched from GitHub at submission.")).toBeNull();
  });

  it("are hidden with a GitHub pull request link, and typed values are not sent", async () => {
    await openCreateForm();
    change("Changed files", "typed.txt");
    change("Diff / change summary", "+typed");
    change("Pull/merge request URL", PR);

    expect(screen.getByText("Changed files and diff will be fetched from GitHub at submission.")).toBeTruthy();
    expect(screen.queryByLabelText("Changed files")).toBeNull();
    expect(screen.queryByLabelText("Diff / change summary")).toBeNull();

    // Removing the link shows the fields again, empty.
    change("Pull/merge request URL", "");
    expect(field("Changed files").value).toBe("");
    expect(field("Diff / change summary").value).toBe("");
  });

  it("create sends the pull request link without manual diff values", async () => {
    service.create.mockResolvedValue({ id: 8 });
    await openCreateForm();
    change("Request Title", "T");
    change("Description", "D");
    change("Target System", "S");
    await waitFor(() => expect(screen.getAllByRole("option", { name: /Sam Senior/ }).length).toBe(1));
    change("Assigned Reviewer", "2");
    change("Diff / change summary", "+typed");
    change("Pull/merge request URL", PR);
    fireEvent.click(screen.getByRole("button", { name: "Create Request" }));

    await waitFor(() => expect(service.create).toHaveBeenCalled());
    const git = service.create.mock.calls[0][0].git_context;
    expect(git).toEqual({ pull_request_url: PR });
  });

  it("edit clears stored manual values when a pull request link is added", async () => {
    auth.user = CREATOR;
    service.update.mockResolvedValue(DRAFT);
    renderAt("/requests/7/edit");
    await waitFor(() => expect(field("Assigned Reviewer").value).toBe("3"));
    change("Pull/merge request URL", PR);
    fireEvent.click(screen.getByRole("button", { name: "Save Changes" }));

    await screen.findByText("Draft saved.");
    expect(service.saveGitContext).toHaveBeenCalledWith("7", expect.objectContaining({
      pull_request_url: PR, changed_files_summary: "", diff_text: "",
    }));
  });

  it("stay for a link that is not a GitHub pull request (nothing is fetched)", async () => {
    await openCreateForm();
    change("Pull/merge request URL", "https://gitlab.com/org/repo/-/merge_requests/7");
    expect(field("Changed files")).toBeTruthy();
    expect(field("Diff / change summary")).toBeTruthy();
  });
});
