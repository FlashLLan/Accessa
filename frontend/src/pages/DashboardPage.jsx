import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

export default function DashboardPage() {
  const { user, token } = useAuth();

  return (
    <div className="page-card">
      <h2 className="page-title">Dashboard</h2>
      <p className="page-subtitle">
        Welcome to Accessa. This is your control panel for navigating requests,
        reviews, and user management while the backend features are still being
        connected.
      </p>

      <div className="page-grid">
        <div className="stat-card">
          <span className="stat-label">Current user</span>
          <div className="stat-value">{user?.name || "Unknown"}</div>
        </div>

        <div className="stat-card">
          <span className="stat-label">Role</span>
          <div className="stat-value" style={{ textTransform: "capitalize" }}>
            {user?.role || "Unknown"}
          </div>
        </div>

        <div className="stat-card">
          <span className="stat-label">Auth status</span>
          <div className="stat-value">{token ? "Active" : "Missing"}</div>
        </div>
      </div>

      <div className="quick-links">
        <Link to="/requests" className="quick-link">
          View Requests
        </Link>
        <Link to="/requests/new" className="quick-link">
          Create Request
        </Link>
        {(user?.role === "admin" ||
          user?.role === "lead" ||
          user?.role === "senior") && (
          <Link to="/review" className="quick-link">
            Open Review Queue
          </Link>
        )}
        {user?.role === "admin" && (
          <Link to="/admin/users" className="quick-link">
            Manage Users
          </Link>
        )}
        <Link to="/account" className="quick-link">
          My Account
        </Link>
      </div>

      <div className="details-section" style={{ marginTop: "24px" }}>
        <h3 className="details-section-title">Account Summary</h3>
        <div className="details-grid" style={{ marginBottom: "16px" }}>
          <div className="detail-box">
            <span className="detail-label">Name</span>
            <strong>{user?.name || "Unknown"}</strong>
          </div>
          <div className="detail-box">
            <span className="detail-label">Role</span>
            <strong style={{ textTransform: "capitalize" }}>{user?.role || "Unknown"}</strong>
          </div>
        </div>
        <div className="page-actions">
          <Link to="/account" className="btn btn-secondary">
            Manage account
          </Link>
        </div>
      </div>
    </div>
  );
}