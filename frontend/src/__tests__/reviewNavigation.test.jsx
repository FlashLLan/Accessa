// The Review item and the /review route: mid reviewers are included, and anyone
// with requests currently waiting for their decision sees the item.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const auth = vi.hoisted(() => ({ user: null }));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: auth.user, isAuthenticated: true, authLoading: false }),
}));

const { default: Sidebar } = await import("../components/layout/Sidebar");
const { default: RoleGuard } = await import("../components/common/RoleGuard");
const { REVIEWER_ROLES, hasPendingReviews } = await import("../utils/requestPermissions");

afterEach(cleanup);

function renderSidebar(user) {
  auth.user = user;
  render(<MemoryRouter><Sidebar /></MemoryRouter>);
  return screen.queryByRole("link", { name: /^Review/ });
}

function openReview(user) {
  auth.user = user;
  render(
    <MemoryRouter initialEntries={["/review"]}>
      <Routes>
        <Route element={<RoleGuard allowedRoles={REVIEWER_ROLES} allowIf={hasPendingReviews} />}>
          <Route path="/review" element={<p>review queue</p>} />
        </Route>
        <Route path="/dashboard" element={<p>dashboard</p>} />
      </Routes>
    </MemoryRouter>
  );
  return screen.getByText(/review queue|dashboard/).textContent;
}

describe("Review sidebar item", () => {
  it.each(["mid", "senior", "lead", "admin", "junior"])(
    "is shown to a %s with requests waiting for their review, with the count",
    (role) => {
      const link = renderSidebar({ role, pending_reviews_count: 2 });
      expect(link).toBeTruthy();
      expect(link.textContent).toBe("Review (2)");
      expect(link.getAttribute("href")).toBe("/review");
    }
  );

  it.each(["mid", "senior", "lead", "admin", "junior"])(
    "is hidden from a %s with nothing to review",
    (role) => {
      expect(renderSidebar({ role, pending_reviews_count: 0 })).toBeNull();
    }
  );
});

describe("/review route", () => {
  it.each(["mid", "senior", "lead", "admin"])("is open to a %s even with an empty queue", (role) => {
    expect(openReview({ role, pending_reviews_count: 0 })).toBe("review queue");
  });

  it("is open to anyone with requests waiting for their review", () => {
    expect(openReview({ role: "junior", pending_reviews_count: 1 })).toBe("review queue");
  });

  it("redirects a junior with nothing to review to the dashboard", () => {
    expect(openReview({ role: "junior", pending_reviews_count: 0 })).toBe("dashboard");
  });
});
