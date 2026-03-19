import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";

export default function Topbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <header className="topbar">
      <div>
        <p className="topbar-kicker">Change Management Platform</p>
        <h1 className="topbar-title">Welcome back</h1>
      </div>

      <div className="topbar-actions">
        <div className="topbar-user">
          <span className="topbar-user-name">{user?.name || "Test User"}</span>
          <span className="topbar-user-role">{user?.role || "unknown"}</span>
        </div>

        <button className="btn btn-secondary" onClick={handleLogout}>
          Logout
        </button>
      </div>
    </header>
  );
}