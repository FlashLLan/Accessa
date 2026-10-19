import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { workspaceLoginPath } from "../../utils/storage";

export default function Topbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    const slug = user?.workspace?.slug;
    logout();
    navigate(workspaceLoginPath(slug));
  };

  return (
    <header className="topbar">
      <div>
        <p className="topbar-kicker">{user?.workspace?.name || "Change Management Platform"}</p>
        <h1 className="topbar-title">Welcome back</h1>
      </div>

      <div className="topbar-actions">
        <Link to="/account" className="topbar-user-link">
          <div className="topbar-user">
            <span className="topbar-user-name">{user?.name || "Test User"}</span>
            <span className="topbar-user-role">{user?.role || "unknown"}</span>
          </div>
        </Link>

        <button className="btn btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}