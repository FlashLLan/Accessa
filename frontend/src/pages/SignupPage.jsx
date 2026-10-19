import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { signupRequest } from "../api/auth";
import { extractApiError } from "../utils/apiError";

// Mirrors the backend rules (workspace_service.py): 3-32 chars of a-z, 0-9 and '-',
// not starting or ending with '-', and not a reserved word.
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/;
const RESERVED_SLUGS = new Set(["admin", "api", "login", "signup", "w", "www", "static", "assets", "health", "docs"]);

function slugify(name) {
  return name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32)
    .replace(/-+$/g, "");
}

function slugProblem(slug) {
  if (!SLUG_PATTERN.test(slug)) {
    return "Use 3-32 lowercase letters, digits or '-', not starting or ending with '-'.";
  }
  if (RESERVED_SLUGS.has(slug)) {
    return "This address is reserved. Please choose another one.";
  }
  return "";
}

export default function SignupPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [workspaceName, setWorkspaceName] = useState("");
  const [workspaceSlug, setWorkspaceSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createdSlug, setCreatedSlug] = useState("");
  const [copied, setCopied] = useState(false);

  const loginAddress = `${window.location.origin}/w/${createdSlug || workspaceSlug || "your-team"}`;

  const handleNameChange = (value) => {
    setWorkspaceName(value);
    if (!slugEdited) setWorkspaceSlug(slugify(value));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    const slug = workspaceSlug.trim().toLowerCase();
    const problem = slugProblem(slug);
    if (problem) {
      setError(problem);
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);

    try {
      const data = await signupRequest({
        workspaceName: workspaceName.trim(),
        workspaceSlug: slug,
        fullName,
        email,
        password,
      });

      await login(data.access_token);
      setCreatedSlug(slug);
    } catch (error) {
      console.error("Signup failed", error);

      const message =
        error?.response?.status === 429
          ? "Too many attempts. Please wait a moment and try again."
          : extractApiError(error, "Could not create the workspace. Please try again.");

      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(loginAddress);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  if (createdSlug) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-header">
            <p className="auth-kicker">Accessa</p>
            <h1>Workspace created</h1>
            <p className="auth-subtitle">
              Your team signs in at this address. Share it with the people you add
              under User Management.
            </p>
          </div>

          <div className="workspace-address">
            <code>{loginAddress}</code>
            <button type="button" className="btn btn-secondary" onClick={handleCopy}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>

          <button
            type="button"
            className="btn btn-primary auth-submit"
            onClick={() => navigate("/admin/users")}
          >
            Continue to User Management
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-kicker">Accessa</p>
          <h1>Create a workspace</h1>
          <p className="auth-subtitle">
            Register a workspace for your team. You become its administrator and
            create accounts for your team members.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="workspaceName">Workspace name</label>
            <input
              id="workspaceName"
              type="text"
              placeholder="Platform Team"
              value={workspaceName}
              onChange={(e) => handleNameChange(e.target.value)}
              required
              minLength={2}
              maxLength={120}
              autoComplete="organization"
            />
          </div>

          <div className="form-group">
            <label htmlFor="workspaceSlug">Workspace address</label>
            <input
              id="workspaceSlug"
              type="text"
              placeholder="platform-team"
              value={workspaceSlug}
              onChange={(e) => {
                setSlugEdited(true);
                setWorkspaceSlug(e.target.value.toLowerCase());
              }}
              required
              minLength={3}
              maxLength={32}
              autoCapitalize="none"
              spellCheck={false}
            />
            <small className="form-hint">Login page: {loginAddress}</small>
          </div>

          <div className="form-group">
            <label htmlFor="fullName">Your full name</label>
            <input
              id="fullName"
              type="text"
              placeholder="Jane Doe"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              maxLength={100}
              autoComplete="name"
            />
          </div>

          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              placeholder="you@company.com"
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
              placeholder="At least 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirmPassword">Confirm password</label>
            <input
              id="confirmPassword"
              type="password"
              placeholder="Repeat your password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
            />
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="btn btn-primary auth-submit" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating workspace..." : "Sign up"}
          </button>
        </form>

        <p className="auth-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
