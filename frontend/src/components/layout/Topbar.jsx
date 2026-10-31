import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { workspaceLoginPath } from "../../utils/storage";
import { formatRole } from "../../utils/roleUtils";

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
        <p className="topbar-kicker">Workspace</p>
        <h1 className="topbar-title">{user?.workspace?.name || "Accessa"}</h1>
      </div>

      <div className="topbar-actions">
        <Link to="/account" className="topbar-user-link">
          <div className="topbar-user">
            <span className="topbar-user-name">{user?.name || user?.email || ""}</span>
            <span className="topbar-user-role">{formatRole(user?.role, "")}</span>
          </div>
        </Link>

        <button className="btn btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}