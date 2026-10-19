import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { loginRequest } from "../api/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { slug = "" } = useParams();
  const workspaceSlug = slug.trim().toLowerCase();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const data = await loginRequest({ workspaceSlug, email, password });

      await login(data.access_token);
      navigate(data.must_change_password ? "/change-password" : "/dashboard");
    } catch (error) {
      console.error("Login failed", error);

      // The backend returns one generic 401 for every failure (unknown workspace,
      // unknown email, wrong password, inactive account) by design.
      const message =
        error?.response?.status === 429
          ? "Too many login attempts. Please wait a moment and try again."
          : "Invalid email or password.";

      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-kicker">Accessa</p>
          <h1>Sign in</h1>
          <p className="auth-workspace">
            Workspace <code>{workspaceSlug}</code>
          </p>
          <p className="auth-subtitle">
            Log in with the account your workspace administrator created for you.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              placeholder="admin@test.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn btn-primary auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Signing in..." : "Login"}
          </button>
        </form>

        <p className="auth-switch">
          Not your workspace? <Link to="/login">Choose another</Link>
          {" · "}
          New team? <Link to="/signup">Sign up</Link>
        </p>

        <div className="auth-help">
          <span>Test accounts:</span>
          <code>admin@test.com</code>
          <code>lead@test.com</code>
          <code>senior@test.com</code>
          <code>mid@test.com</code>
          <code>junior@test.com</code>
        </div>
      </div>
    </div>
  );
}