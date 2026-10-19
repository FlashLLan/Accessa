import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { changePassword } from "../api/users";
import { extractApiError } from "../utils/apiError";

// Shown when an admin created the account with an initial password: the backend
// blocks every other endpoint until it is changed (must_change_password).
export default function ChangePasswordPage() {
  const { user, refreshMe, logout } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ current_password: "", new_password: "", confirm_password: "" });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (form.new_password.length < 8) {
      setError("New password must be at least 8 characters.");
      return;
    }
    if (form.new_password !== form.confirm_password) {
      setError("New password and confirmation do not match.");
      return;
    }
    if (form.new_password === form.current_password) {
      setError("New password must be different from your current password.");
      return;
    }

    setIsSubmitting(true);
    try {
      await changePassword(form);
      await refreshMe();
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(extractApiError(err, "Failed to change password."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-kicker">{user?.workspace?.name || "Accessa"}</p>
          <h1>Set your password</h1>
          <p className="auth-subtitle">
            Your account was created with an initial password. Choose your own
            password to continue.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="current_password">Initial password</label>
            <input
              id="current_password"
              name="current_password"
              type="password"
              value={form.current_password}
              onChange={handleChange}
              required
              autoComplete="current-password"
            />
          </div>

          <div className="form-group">
            <label htmlFor="new_password">New password</label>
            <input
              id="new_password"
              name="new_password"
              type="password"
              placeholder="At least 8 characters"
              value={form.new_password}
              onChange={handleChange}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirm_password">Confirm new password</label>
            <input
              id="confirm_password"
              name="confirm_password"
              type="password"
              value={form.confirm_password}
              onChange={handleChange}
              required
              autoComplete="new-password"
            />
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn btn-primary auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving..." : "Save password"}
          </button>
        </form>

        <p className="auth-switch">
          <button type="button" className="link-button" onClick={logout}>
            Log out
          </button>
        </p>
      </div>
    </div>
  );
}
