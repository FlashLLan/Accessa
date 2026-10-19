import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getLastWorkspaceSlug } from "../utils/storage";

// /login: every workspace has its own login address (/w/<slug>). This page only
// asks which workspace to go to.
export default function FindWorkspacePage() {
  const navigate = useNavigate();
  const [slug, setSlug] = useState(getLastWorkspaceSlug);

  const handleSubmit = (e) => {
    e.preventDefault();
    const clean = slug.trim().toLowerCase();
    if (clean) navigate(`/w/${encodeURIComponent(clean)}`);
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-kicker">Accessa</p>
          <h1>Sign in</h1>
          <p className="auth-subtitle">
            Enter your workspace address. Your administrator shared it with you,
            for example <code>{window.location.host}/w/acme</code>.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="workspace">Workspace</label>
            <input
              id="workspace"
              type="text"
              placeholder="acme"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              required
              autoComplete="organization"
              autoCapitalize="none"
              spellCheck={false}
            />
          </div>

          <button className="btn btn-primary auth-submit" type="submit">
            Continue
          </button>
        </form>

        <p className="auth-switch">
          New team? <Link to="/signup">Create a workspace</Link>
        </p>
      </div>
    </div>
  );
}
