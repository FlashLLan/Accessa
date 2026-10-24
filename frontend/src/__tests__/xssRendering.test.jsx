// XSS hardening: user- and AI-supplied text is rendered as text, never as markup.
// The real RequestDetailsPage (with its GitContext diff and AI Review section) is
// rendered with its data sources mocked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const PAYLOADS = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>"];

const data = vi.hoisted(() => ({ payload: "" }));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({
    user: { id: 99, email: "viewer@test.com", role: "admin", full_name: "Viewer" },
  }),
}));

vi.mock("../api/users.js", () => ({ getReviewers: vi.fn(async () => []) }));

vi.mock("../services/requestsService.js", () => ({
  requestService: {
    getById: vi.fn(async () => ({
      id: 7,
      title: "Request 7",
      description: data.payload,
      status: "pending_review",
      risk_level: "low",
      request_type: "code_change",
      environment: "staging",
      target_system: "api",
      created_at: "2026-10-22T10:00:00",
      creator: { id: 1, full_name: "Creator", email: "c@test.com", role: { name: "junior" } },
      assigned_reviewer: { id: 2, full_name: "Reviewer", email: "r@test.com", role: { name: "mid" } },
      git_context: {
        provider: "github",
        pull_request_url: "https://github.com/octo/demo/pull/7",
        diff_text: [
          "diff --git a/app/x.py b/app/x.py",
          "--- a/app/x.py",
          "+++ b/app/x.py",
          "@@ -1 +1 @@",
          `-${data.payload}`,
          `+${data.payload}`,
          ` ${data.payload}`,
        ].join("\n"),
      },
    })),
    listApprovals: vi.fn(async () => []),
    listReviewActions: vi.fn(async () => []),
    listComments: vi.fn(async () => [
      { id: 1, comment_text: data.payload, created_at: "2026-10-22T10:00:00", user: { full_name: "Commenter" } },
    ]),
  },
}));

vi.mock("../api/changeRequests", () => ({
  generateAiReview: vi.fn(),
  getGitHead: vi.fn(async () => null),
  getAiReviews: vi.fn(async () => [{
    id: 1,
    change_request_id: 7,
    summary: data.payload,
    suggested_risk_level: "high",
    recommended_reviewer_role: "senior",
    impact_area: data.payload,
    red_flags: JSON.stringify([data.payload]),
    verification_checklist: JSON.stringify([data.payload]),
    improvement_suggestions: JSON.stringify([data.payload]),
    model_name: "gpt-test",
    prompt_version: "1.0.0",
    reviewed_commit: "c0ffee0000000000000000000000000000000000",
    review_scope: "changed_files",
    files_reviewed: [{ path: data.payload, source: "changed" }],
    files_skipped: [],
    changed_files_total: 1,
    input_truncated: false,
    secrets_masked: 0,
    generated_by_role: "mid",
    created_at: "2026-10-22T10:00:00",
  }]),
}));

// Imported after the mocks.
const { default: RequestDetailsPage } = await import("../pages/RequestDetailsPage");
const { default: DiffView } = await import("../components/requests/DiffView");

function section(title) {
  return screen.getByRole("heading", { name: title }).closest(".details-section");
}

function expectNoInjectedMarkup(container) {
  // Nothing from the payload became an element or an event handler.
  expect(container.querySelectorAll("script")).toHaveLength(0);
  expect(container.querySelector('img[src="x"]')).toBeNull();
  expect(container.querySelector("[onerror]")).toBeNull();
}

beforeEach(() => {
  vi.spyOn(window, "alert").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe.each(PAYLOADS)("payload %s", (payload) => {
  beforeEach(() => {
    data.payload = payload;
  });

  it("is shown as text in the comment, description, diff and AI result", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/requests/7"]}>
        <Routes>
          <Route path="/requests/:id" element={<RequestDetailsPage />} />
        </Routes>
      </MemoryRouter>
    );

    // Comment
    const comments = await screen.findByRole("heading", { name: "Comments" });
    expect(within(comments.closest(".details-section")).getByText(payload)).toBeTruthy();

    // Request description
    expect(within(section("Description")).getByText(payload).tagName).toBe("P");

    // Diff lines (removed, added, context), each as the text of one line
    const diffLines = [...section("Git Context").querySelectorAll(".diff-line")].map((l) => l.textContent);
    expect(diffLines).toEqual(expect.arrayContaining([`-${payload}`, `+${payload}`, ` ${payload}`]));

    // AI result: summary, impact area, the three lists and a reviewed file name
    const ai = await screen.findByRole("heading", { name: "AI Review" });
    const aiSection = within(ai.closest(".details-section"));
    expect(await aiSection.findByText(payload, { selector: ".ai-review-summary" })).toBeTruthy();
    expect(aiSection.getByText(`Impact: ${payload}`)).toBeTruthy();
    expect(aiSection.getAllByText(payload, { selector: "li" })).toHaveLength(3);
    expect(aiSection.getByText(payload, { selector: ".ai-review-files .git-monospace" })).toBeTruthy();

    expectNoInjectedMarkup(container);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("is shown as text in a diff file name", () => {
    const { container } = render(
      <DiffView text={`--- a/${payload}\n+++ b/${payload}\n+${payload}`} />
    );
    expect(screen.getByText(payload, { selector: ".diff-file-header span" })).toBeTruthy();
    expect(screen.getByText(`+${payload}`)).toBeTruthy();
    expectNoInjectedMarkup(container);
    expect(window.alert).not.toHaveBeenCalled();
  });
});
