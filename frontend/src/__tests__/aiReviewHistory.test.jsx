// AI Review section: switching between stored reviews, and the "nothing
// changed" warning before regenerating with the same commit and scope.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({ getAiReviews: vi.fn(), generateAiReview: vi.fn() }));
vi.mock("../api/changeRequests", () => api);

const { default: AiReviewSection } = await import("../components/requests/AiReviewSection");

const REVIEWER = { id: 2, email: "mid@test.com", role: "mid" };
const REQUEST = {
  id: 7, status: "pending_review", risk_level: "low",
  assigned_reviewer: { id: 2, email: "mid@test.com" },
  git_context: { pull_request_url: "https://github.com/octo/demo/pull/7" },
};

function result(id, summary, extra = {}) {
  return {
    id, change_request_id: 7, summary, suggested_risk_level: "low", recommended_reviewer_role: "mid",
    red_flags: "[]", verification_checklist: "[]", improvement_suggestions: "[]",
    reviewed_commit: "c0ffee0000000000000000000000000000000000", review_scope: "changed_files",
    files_reviewed: [], files_skipped: [], created_at: "2026-10-24T10:00:00", ...extra,
  };
}

const THIRD = result(3, "Third review");
const SECOND = result(2, "Second review");
const FIRST = result(1, "First review");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderSection(results, onError = vi.fn()) {
  api.getAiReviews.mockResolvedValue(results);
  render(<AiReviewSection request={REQUEST} user={REVIEWER} onError={onError} />);
  return onError;
}

const summary = () => document.querySelector(".ai-review-summary").textContent;

describe("AI review history", () => {
  it("starts at the latest review and switches with Older / Newer", async () => {
    renderSection([THIRD, SECOND, FIRST]);
    expect(await screen.findByText("Review 3 of 3 (latest)")).toBeTruthy();
    expect(summary()).toBe("Third review");
    const older = screen.getByRole("button", { name: "◀ Older" });
    const newer = screen.getByRole("button", { name: "Newer ▶" });
    expect(newer.disabled).toBe(true);

    fireEvent.click(older);
    expect(screen.getByText("Review 2 of 3")).toBeTruthy();
    expect(summary()).toBe("Second review");

    fireEvent.click(older);
    expect(screen.getByText("Review 1 of 3")).toBeTruthy();
    expect(summary()).toBe("First review");
    expect(older.disabled).toBe(true);

    fireEvent.click(newer);
    fireEvent.click(newer);
    expect(summary()).toBe("Third review");
  });

  it("shows no navigation for a single review", async () => {
    renderSection([FIRST]);
    await screen.findByText("First review");
    expect(screen.queryByText(/Review \d of \d/)).toBeNull();
  });

  it("a new review is added as the latest and shown", async () => {
    api.generateAiReview.mockResolvedValue(result(4, "Fourth review", { review_scope: "extended" }));
    renderSection([THIRD, SECOND, FIRST]);
    await screen.findByText("Review 3 of 3 (latest)");
    fireEvent.click(screen.getByRole("button", { name: "◀ Older" }));
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));

    expect(await screen.findByText("Review 4 of 4 (latest)")).toBeTruthy();
    expect(summary()).toBe("Fourth review");
    expect(api.generateAiReview).toHaveBeenCalledWith(7, "changed_files", false);
  });
});

describe("Regenerating with nothing changed", () => {
  const UNCHANGED = {
    response: {
      status: 409,
      data: { detail: { code: "ai_review_unchanged", commit: "c0ffee0",
                        message: "Nothing has changed since the latest AI review: same commit c0ffee0 and same scope. Generate it again anyway?" } },
    },
  };

  it("asks first, and 'Generate anyway' sends force", async () => {
    api.generateAiReview.mockRejectedValueOnce(UNCHANGED).mockResolvedValueOnce(result(4, "Forced review"));
    const onError = renderSection([THIRD]);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Nothing has changed");
    expect(dialog.textContent).toContain("same commit c0ffee0");
    expect(onError).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Generate anyway" }));
    await waitFor(() => expect(api.generateAiReview).toHaveBeenLastCalledWith(7, "changed_files", true));
    expect(await screen.findByText("Review 2 of 2 (latest)")).toBeTruthy();
    expect(summary()).toBe("Forced review");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Cancel closes the warning without generating", async () => {
    api.generateAiReview.mockRejectedValueOnce(UNCHANGED);
    renderSection([THIRD]);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(api.generateAiReview).toHaveBeenCalledTimes(1);
    expect(summary()).toBe("Third review");
  });

  it("other errors still go to the toast", async () => {
    api.generateAiReview.mockRejectedValueOnce({ response: { status: 429, data: { detail: "GitHub rate limit reached." } } });
    const onError = renderSection([THIRD]);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith("GitHub rate limit reached."));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says the PR moved and what a new review covers", async () => {
    api.generateAiReview.mockRejectedValueOnce({ response: { status: 409, data: { detail: {
      code: "ai_review_unchanged", head_moved: true, current_head: "dde0dd0", commit: "7c0f3b2",
      message: "The pull request has new commits since submission (now at dde0dd0). This request covers only 7c0f3b2; new changes require a new request. A new AI review will still cover only the submitted commit 7c0f3b2, with the same scope as the latest review. Generate it again anyway?",
    } } } });
    renderSection([THIRD]);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.querySelector("h3").textContent).toBe("The pull request has new commits");
    expect(dialog.textContent).toContain("will still cover only the submitted commit 7c0f3b2");
  });

  it("'Show review n' jumps to the earlier review with the same scope", async () => {
    api.generateAiReview.mockRejectedValueOnce({ response: { status: 409, data: { detail: {
      code: "ai_review_unchanged", head_moved: false, matching_review_number: 1,
      message: "Nothing has changed since review 1 of 3: same commit c0ffee0 and same scope (Changed files). Generate it again anyway?",
    } } } });
    renderSection([THIRD, SECOND, FIRST]);
    fireEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    fireEvent.click(await screen.findByRole("button", { name: "Show review 1" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("Review 1 of 3")).toBeTruthy();
    expect(summary()).toBe("First review");
    expect(api.generateAiReview).toHaveBeenCalledTimes(1);
  });
});
