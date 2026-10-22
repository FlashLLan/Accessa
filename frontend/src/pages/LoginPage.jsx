import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { loginRequest, verifyMfaRequest } from "../api/auth";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { slug = "" } = useParams();
  const workspaceSlug = slug.trim().toLowerCase();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Second step: the short-lived mfa_pending token, kept in memory only.
  const [mfaToken, setMfaToken] = useState("");
  const [code, setCode] = useState("");

  async function finishLogin(data) {
    await login(data.access_token);
    navigate(data.must_change_password ? "/change-password" : "/dashboard");
  }

  function startOver() {
    setMfaToken("");
    setCode("");
    setPassword("");
    setError("");
  }

  const handleVerify = async (e) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      const data = await verifyMfaRequest(mfaToken, code.trim());
      setMfaToken("");
      await finishLogin(data);
    } catch (error) {
      // One generic answer for every failure (wrong, reused or expired code,
      // too many wrong codes), by design.
      setError(
        error?.response?.status === 429
          ? "Too many attempts. Please wait a minute and try again."
          : "Invalid or expired code. After 5 wrong codes, start over."
      );
      setCode("");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const data = await loginRequest({ workspaceSlug, email, password });

      if (data.mfa_required) {
        setMfaToken(data.mfa_token);
        return;
      }
      await finishLogin(data);
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

  if (mfaToken) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-header">
            <p className="auth-kicker">Accessa</p>
            <h1>Enter your code</h1>
            <p className="auth-workspace">
              Workspace <code>{workspaceSlug}</code>
            </p>
            <p className="auth-subtitle">
              Open your authenticator app and enter the 6-digit code for Accessa ({email}).
            </p>
          </div>

          <form className="auth-form" onSubmit={handleVerify}>
            <div className="form-group">
              <label htmlFor="mfa_code">6-digit code</label>
              <input
                id="mfa_code"
                className="mfa-code-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                placeholder="123456"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                required
                autoFocus
              />
            </div>

            {error && <div className="auth-error">{error}</div>}

            <button className="btn btn-primary auth-submit" type="submit" disabled={isSubmitting || code.length !== 6}>
              {isSubmitting ? "Checking..." : "Verify"}
            </button>
          </form>

          <p className="auth-switch">
            <button type="button" className="link-button" onClick={startOver}>
              Start over
            </button>
          </p>
        </div>
      </div>
    );
  }

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