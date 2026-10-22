import { NavLink } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { hasPendingReviews } from "../../utils/requestPermissions";

export default function Sidebar() {
  const { user } = useAuth();

  const role = user?.role;

  const navItems = [
    {
      to: "/dashboard",
      label: "Dashboard",
      roles: ["admin", "lead", "senior", "junior", "mid"],
    },
    {
      to: "/requests",
      label: "Requests",
      roles: ["admin", "lead", "senior", "junior", "mid"],
      end: true,
    },
    {
      to: "/requests/new",
      label: "Create Request",
      roles: ["admin", "lead", "senior", "junior", "mid"],
    },
    {
      // Shown to anyone with requests currently waiting for their decision.
      to: "/review",
      label: `Review (${user?.pending_reviews_count ?? 0})`,
      visible: hasPendingReviews,
    },
    {
      to: "/admin/users",
      label: "User Management",
      roles: ["admin"],
    },
    {
      to: "/admin/audit-log",
      label: "Audit Log",
      roles: ["admin"],
    },
  ];

  const visibleItems = navItems.filter((item) =>
    item.visible ? item.visible(user) : item.roles.includes(role)
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-badge">A</div>
        <div>
          <h2>Accessa</h2>
          <p>Access workflows</p>
        </div>
      </div>

      <nav className="sidebar-nav">
        {visibleItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? "active" : ""}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="sidebar-user-card">
          <span className="sidebar-user-label">Current role</span>
          <strong>{role || "unknown"}</strong>
        </div>
      </div>
    </aside>
  );
}