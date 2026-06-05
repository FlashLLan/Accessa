import { useEffect, useState } from "react";
import Toast from "../components/common/Toast";
import { updateMe, changePassword, getMyStats } from "../api/users";
import { useAuth } from "../hooks/useAuth";
import { formatDate } from "../utils/requestPresentation";
import { extractApiError } from "../utils/apiError";

export default function AccountPage() {
  const { user, refreshMe } = useAuth();

  const [fullName, setFullName] = useState(user?.full_name || "");
  const [isSavingProfile, setIsSavingProfile] = useState(false);

  const [passwordForm, setPasswordForm] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });
  const [isChangingPassword, setIsChangingPassword] = useState(false);

  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const [toast, setToast] = useState({ message: "", type: "error" });

  useEffect(() => {
    loadStats();
  }, []);

  useEffect(() => {
    if (user?.full_name) setFullName(user.full_name);
  }, [user?.full_name]);

  async function loadStats() {
    try {
      setStatsLoading(true);
      const data = await getMyStats();
      setStats(data);
    } catch (err) {
      console.error("Failed to load stats", err);
    } finally {
      setStatsLoading(false);
    }
  }

  async function handleSaveProfile(e) {
    e.preventDefault();
    const trimmed = fullName.trim();
    if (!trimmed) {
      setToast({ message: "Full name cannot be empty.", type: "error" });
      return;
    }
    try {
      setIsSavingProfile(true);
      await updateMe({ full_name: trimmed });
      await refreshMe();
      setToast({ message: "Profile updated successfully.", type: "success" });
    } catch (err) {
      setToast({
        message: extractApiError(err, "Failed to update profile."),
        type: "error",
      });
    } finally {
      setIsSavingProfile(false);
    }
  }

  async function handleChangePassword(e) {
    e.preventDefault();
    const { current_password, new_password, confirm_password } = passwordForm;

    if (!current_password) {
      setToast({ message: "Current password is required.", type: "error" });
      return;
    }
    if (!new_password) {
      setToast({ message: "New password is required.", type: "error" });
      return;
    }
    if (new_password.length < 8) {
      setToast({ message: "New password must be at least 8 characters.", type: "error" });
      return;
    }
    if (new_password !== confirm_password) {
      setToast({ message: "New password and confirmation do not match.", type: "error" });
      return;
    }
    if (new_password === current_password) {
      setToast({ message: "New password must be different from your current password.", type: "error" });
      return;
    }

    try {
      setIsChangingPassword(true);
      await changePassword({ current_password, new_password, confirm_password });
      setPasswordForm({ current_password: "", new_password: "", confirm_password: "" });
      setToast({ message: "Password changed successfully.", type: "success" });
    } catch (err) {
      setToast({
        message: extractApiError(err, "Failed to change password."),
        type: "error",
      });
    } finally {
      setIsChangingPassword(false);
    }
  }

  function handlePasswordFieldChange(e) {
    const { name, value } = e.target;
    setPasswordForm((prev) => ({ ...prev, [name]: value }));
  }

  const isAdmin = user?.role === "admin";
  const nameUnchanged = fullName.trim() === (user?.full_name || "");

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Account</h2>
          <p className="page-subtitle">Manage your profile and account security.</p>
        </div>
      </div>

      {/* Profile Information */}
      <div className="details-section">
        <h3 className="details-section-title">Profile Information</h3>

        <div className="details-grid" style={{ marginBottom: "20px" }}>
          <div className="detail-box">
            <span className="detail-label">Email</span>
            <strong>{user?.email}</strong>
          </div>
          <div className="detail-box">
            <span className="detail-label">Role</span>
            <strong style={{ textTransform: "capitalize" }}>{user?.role}</strong>
          </div>
          <div className="detail-box">
            <span className="detail-label">Status</span>
            <strong style={{ color: user?.is_active !== false ? "var(--success)" : "var(--danger)" }}>
              {user?.is_active !== false ? "Active" : "Inactive"}
            </strong>
          </div>
          <div className="detail-box">
            <span className="detail-label">Member Since</span>
            <strong>{user?.created_at ? formatDate(user.created_at) : "—"}</strong>
          </div>
        </div>

        <form onSubmit={handleSaveProfile}>
          <div className="form-group" style={{ marginBottom: "16px" }}>
            <label htmlFor="fullName">Full Name</label>
            <input
              id="fullName"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Your full name"
              required
            />
          </div>
          <div className="page-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isSavingProfile || nameUnchanged}
            >
              {isSavingProfile ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </form>
      </div>

      {/* Change Password */}
      <div className="details-section">
        <h3 className="details-section-title">Change Password</h3>

        <form onSubmit={handleChangePassword}>
          <div className="form-group" style={{ marginBottom: "16px" }}>
            <label htmlFor="current_password">Current Password</label>
            <input
              id="current_password"
              name="current_password"
              type="password"
              value={passwordForm.current_password}
              onChange={handlePasswordFieldChange}
              placeholder="Enter current password"
              autoComplete="current-password"
            />
          </div>
          <div className="form-row" style={{ marginBottom: "16px" }}>
            <div className="form-group">
              <label htmlFor="new_password">New Password</label>
              <input
                id="new_password"
                name="new_password"
                type="password"
                value={passwordForm.new_password}
                onChange={handlePasswordFieldChange}
                placeholder="At least 8 characters"
                autoComplete="new-password"
              />
            </div>
            <div className="form-group">
              <label htmlFor="confirm_password">Confirm New Password</label>
              <input
                id="confirm_password"
                name="confirm_password"
                type="password"
                value={passwordForm.confirm_password}
                onChange={handlePasswordFieldChange}
                placeholder="Repeat new password"
                autoComplete="new-password"
              />
            </div>
          </div>
          <div className="page-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isChangingPassword}
            >
              {isChangingPassword ? "Changing..." : "Change Password"}
            </button>
          </div>
        </form>
      </div>

      {/* My Statistics */}
      <div className="details-section">
        <h3 className="details-section-title">My Statistics</h3>

        {statsLoading ? (
          <div className="empty-state">Loading statistics...</div>
        ) : !stats ? (
          <div className="empty-state">Could not load statistics.</div>
        ) : (
          <>
            <p className="account-stats-group">Requests</p>
            <div className="page-grid" style={{ marginBottom: "24px" }}>
              <div className="stat-card">
                <span className="stat-label">Created</span>
                <div className="stat-value">{stats.requests_created}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Pending</span>
                <div className="stat-value">{stats.pending_requests}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Approved</span>
                <div className="stat-value">{stats.approved_requests}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Rejected</span>
                <div className="stat-value">{stats.rejected_requests}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Comments Written</span>
                <div className="stat-value">{stats.comments_written}</div>
              </div>
            </div>

            <p className="account-stats-group">Reviews</p>
            <div className="page-grid" style={{ marginBottom: isAdmin && stats.users_created !== null ? "24px" : "0" }}>
              <div className="stat-card">
                <span className="stat-label">Requests Reviewed</span>
                <div className="stat-value">{stats.requests_reviewed}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Approved</span>
                <div className="stat-value">{stats.approved_decisions}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Rejected</span>
                <div className="stat-value">{stats.rejected_decisions}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Delegations</span>
                <div className="stat-value">{stats.delegations_performed}</div>
              </div>
              <div className="stat-card">
                <span className="stat-label">Escalations</span>
                <div className="stat-value">{stats.escalations_performed}</div>
              </div>
            </div>

            {isAdmin && stats.users_created !== null && (
              <>
                <p className="account-stats-group">Admin Actions</p>
                <div className="page-grid">
                  <div className="stat-card">
                    <span className="stat-label">Users Created</span>
                    <div className="stat-value">{stats.users_created}</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Deactivations</span>
                    <div className="stat-value">{stats.users_deactivated}</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Role Changes</span>
                    <div className="stat-value">{stats.role_changes_performed}</div>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Actions Logged</span>
                    <div className="stat-value">{stats.admin_actions_logged}</div>
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>

      <Toast
        message={toast.message}
        type={toast.type}
        onClose={() => setToast({ message: "", type: "error" })}
      />
    </div>
  );
}
