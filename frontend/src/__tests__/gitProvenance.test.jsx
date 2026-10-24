// The request page says where the diff and file list come from (FR-21).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const data = vi.hoisted(() => ({ git: null, head: null }));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: 99, email: "v@test.com", role: "admin" }, refreshMe: vi.fn() }),
}));
vi.mock("../api/users.js", () => ({ getReviewers: vi.fn(async () => []) }));
vi.mock("../api/changeRequests", () => ({
  getAiReviews: vi.fn(async () => []),
  generateAiReview: vi.fn(),
  getGitHead: vi.fn(async () => {
    if (data.head instanceof Error) throw data.head;
    return data.head;
  }),
}));
vi.mock("../services/requestsService.js", () => ({
  requestService: {
    getById: vi.fn(async () => ({
      id: 7, title: "R", description: "d", status: "pending_review", risk_level: "low",
      request_type: "code_change", environment: "staging", target_system: "api",
      created_at: "2026-10-24T10:00:00",
      creator: { id: 1, email: "c@test.com", role: { name: "junior" } },
      assigned_reviewer: { id: 2, email: "r@test.com", role: { name: "mid" } },
      git_context: data.git,
    })),
    listApprovals: vi.fn(async () => []),
    listReviewActions: vi.fn(async () => []),
    listComments: vi.fn(async () => []),
  },
}));

const { default: RequestDetailsPage } = await import("../pages/RequestDetailsPage");

afterEach(cleanup);

function renderPage(git, head = null) {
  data.git = git;
  data.head = head;
  render(
    <MemoryRouter initialEntries={["/requests/7"]}>
      <Routes><Route path="/requests/:id" element={<RequestDetailsPage />} /></Routes>
    </MemoryRouter>
  );
}

describe("Git context provenance", () => {
  it("shows the GitHub commit and fetch time", async () => {
    renderPage({ source: "github", commit_hash: "c0ffee1234567890", fetched_at: "2026-10-24T09:30:00",
                 diff_text: "diff --git a/x b/x\n--- a/x\n+++ b/x\n+y", changed_files_summary: "1 changed files" });
    const line = await screen.findByText(/^Fetched from GitHub at commit c0ffee1 \(/);
    expect(line.className).toContain("git-provenance-verified");
    expect(screen.queryByText("Entered by the requester, not verified")).toBeNull();
  });

  it("marks manually entered data as not verified", async () => {
    renderPage({ source: "manual", diff_text: "+pasted" });
    expect(await screen.findByText("Entered by the requester, not verified")).toBeTruthy();
    expect(screen.queryByText(/Fetched from GitHub/)).toBeNull();
  });

  it("shows nothing when there is no diff or file list", async () => {
    renderPage({ source: "manual", branch_name: "feature/x" });
    await screen.findByText("Git Context");
    expect(screen.queryByText(/Entered by the requester|Fetched from GitHub/)).toBeNull();
  });
});

const GITHUB_GIT = {
  source: "github", commit_hash: "7c0f3b2aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", fetched_at: "2026-10-24T09:30:00",
  pull_request_url: "https://github.com/octo/demo/pull/1",
  diff_text: "diff --git a/x b/x\n--- a/x\n+++ b/x\n+y", changed_files_summary: "1 changed files",
};
const MOVED_TEXT = /The pull request has new commits since submission \(now at dde0dd0\)/;

describe("PR moved on since submission", () => {
  it("shows a warning above the diff when the head moved", async () => {
    renderPage(GITHUB_GIT, { applicable: true, head_moved: true,
      stored_commit: GITHUB_GIT.commit_hash, current_head: "dde0dd0bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" });
    const warning = await screen.findByText(MOVED_TEXT);
    expect(warning.textContent).toContain("This request covers only 7c0f3b2; new changes require a new request.");
    // Above the diff.
    const diff = document.querySelector(".diff-view");
    expect(warning.compareDocumentPosition(diff) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows no warning when the head is unchanged", async () => {
    renderPage(GITHUB_GIT, { applicable: true, head_moved: false,
      stored_commit: GITHUB_GIT.commit_hash, current_head: GITHUB_GIT.commit_hash });
    await screen.findByText(/^Fetched from GitHub/);
    expect(screen.queryByText(MOVED_TEXT)).toBeNull();
  });

  it("still loads the page when GitHub cannot be checked", async () => {
    renderPage(GITHUB_GIT, new Error("Network Error"));
    expect(await screen.findByText(/^Fetched from GitHub at commit 7c0f3b2/)).toBeTruthy();
    expect(screen.queryByText(MOVED_TEXT)).toBeNull();
    expect(document.querySelector(".auth-error")).toBeNull();
  });
});

