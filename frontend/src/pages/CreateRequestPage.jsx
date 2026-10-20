import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Toast from "../components/common/Toast";
import { requestService } from "../services/requestsService.js";
import { getReviewers } from "../api/users";
import { useAuth } from "../hooks/useAuth";
import { extractApiError } from "../utils/apiError";

const initialForm = {
  title: "",
  description: "",
  request_type: "access_change",
  target_system: "",
  environment: "development",
  risk_level: "medium",
  assigned_reviewer_id: "",
};

const initialGitForm = {
  provider: "",
  repository_url: "",
  repository_name: "",
  branch_name: "",
  target_branch: "",
  commit_hash: "",
  pull_request_url: "",
  changed_files_summary: "",
  diff_text: "",
};

export default function CreateRequestPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [form, setForm] = useState(initialForm);
  const [gitOpen, setGitOpen] = useState(false);
  const [gitForm, setGitForm] = useState(initialGitForm);
  const [reviewers, setReviewers] = useState([]);
  const [isLoadingReviewers, setIsLoadingReviewers] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [toastError, setToastError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    async function loadReviewers() {
      try {
        setIsLoadingReviewers(true);
        setError("");
        const data = await getReviewers(user?.role, form.risk_level);
        setReviewers(data);
      } catch (err) {
        console.error("Failed to load reviewers", err);
        setError(
          extractApiError(err, "Failed to load reviewers. Please try again.")
        );
      } finally {
        setIsLoadingReviewers(false);
      }
    }

    if (user?.role) loadReviewers();
  }, [user?.role, form.risk_level]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: value,
      ...(name === "risk_level" ? { assigned_reviewer_id: "" } : {}),
    }));
  };

  const handleGitChange = (e) => {
    const { name, value } = e.target;
    setGitForm((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      setIsSubmitting(true);
      setError("");
      setSuccessMessage("");

      const payload = {
        ...form,
        assigned_reviewer_id: Number(form.assigned_reviewer_id),
      };

      // Include git_context only if at least one field is non-empty
      const gitEntries = Object.entries(gitForm).filter(([, v]) => v.trim() !== "");
      if (gitEntries.length > 0) {
        const gitPayload = {};
        gitEntries.forEach(([k, v]) => { gitPayload[k] = v; });
        payload.git_context = gitPayload;
      }

      const created = await requestService.create(payload);

      setSuccessMessage("Request created successfully.");
      setForm(initialForm);
      setGitForm(initialGitForm);

      setTimeout(() => {
        navigate(`/requests/${created.id}`);
      }, 600);
    } catch (err) {
      console.error("Failed to create request", err);
      setToastError(extractApiError(err, "Failed to create the request. Please check your input."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="page-card">
      <h2 className="page-title">Create Request</h2>
      <p className="page-subtitle">
        Submit a new change request using the real backend API.
      </p>

      {error && <div className="auth-error">{error}</div>}
      {successMessage && <div className="success-banner">{successMessage}</div>}
      <Toast message={toastError} type="error" onClose={() => setToastError("")} />

      <form className="request-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="title">Request Title</label>
          <input
            id="title"
            name="title"
            type="text"
            value={form.title}
            onChange={handleChange}
            placeholder="Grant staging dashboard access"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            name="description"
            rows="6"
            value={form.description}
            onChange={handleChange}
            placeholder="Describe the requested change and the reason for it"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="target_system">Target System</label>
          <input
            id="target_system"
            name="target_system"
            type="text"
            value={form.target_system}
            onChange={handleChange}
            placeholder="Grafana / Internal API / VPN Gateway"
            required
          />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="request_type">Request Type</label>
            <select
              id="request_type"
              name="request_type"
              value={form.request_type}
              onChange={handleChange}
            >
              <option value="access_change">Access Change</option>
              <option value="configuration_change">Configuration Change</option>
              <option value="code_change">Code Change</option>
              <option value="security_change">Security Change</option>
              <option value="administrative_change">Administrative Change</option>
              <option value="deployment_change">Deployment Change</option>
              <option value="resource_change">Resource Change</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="environment">Environment</label>
            <select
              id="environment"
              name="environment"
              value={form.environment}
              onChange={handleChange}
            >
              <option value="development">Development</option>
              <option value="staging">Staging</option>
              <option value="production">Production</option>
            </select>
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="risk_level">Risk Level</label>
            <select
              id="risk_level"
              name="risk_level"
              value={form.risk_level}
              onChange={handleChange}
            >
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="assigned_reviewer_id">Assigned Reviewer</label>
            <select
              id="assigned_reviewer_id"
              name="assigned_reviewer_id"
              value={form.assigned_reviewer_id}
              onChange={handleChange}
              required
              disabled={isLoadingReviewers}
            >
              <option value="">
                {isLoadingReviewers ? "Loading reviewers..." : "Select reviewer"}
              </option>
              {reviewers.map((reviewer) => (
                <option key={reviewer.id} value={reviewer.id}>
                  {reviewer.full_name || reviewer.email} ({reviewer.role?.name || "role"})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Git-linked context — collapsible, optional */}
        <div className="git-context-section">
          <button
            type="button"
            className="git-context-toggle"
            onClick={() => setGitOpen((prev) => !prev)}
            aria-expanded={gitOpen}
          >
            <span>Git-linked context</span>
            <span className="git-context-badge">optional</span>
            <span className="git-context-chevron">{gitOpen ? "▲" : "▼"}</span>
          </button>

          {gitOpen && (
            <div className="git-context-fields">
              <p className="git-context-hint">
                Optional Git metadata can help reviewers understand the technical
                context. Do not paste secrets, tokens, passwords, or private keys.
              </p>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="gc_provider">Provider</label>
                  <select
                    id="gc_provider"
                    name="provider"
                    value={gitForm.provider}
                    onChange={handleGitChange}
                  >
                    <option value="">Select provider</option>
                    <option value="github">GitHub</option>
                    <option value="gitlab">GitLab</option>
                    <option value="bitbucket">Bitbucket</option>
                    <option value="azure_devops">Azure DevOps</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                <div className="form-group">
                  <label htmlFor="gc_repository_name">Repository name</label>
                  <input
                    id="gc_repository_name"
                    name="repository_name"
                    type="text"
                    value={gitForm.repository_name}
                    onChange={handleGitChange}
                    placeholder="my-service"
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="gc_repository_url">Repository URL</label>
                <input
                  id="gc_repository_url"
                  name="repository_url"
                  type="url"
                  value={gitForm.repository_url}
                  onChange={handleGitChange}
                  placeholder="https://github.com/org/my-service"
                />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label htmlFor="gc_branch_name">Branch name</label>
                  <input
                    id="gc_branch_name"
                    name="branch_name"
                    type="text"
                    value={gitForm.branch_name}
                    onChange={handleGitChange}
                    placeholder="feature/my-change"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="gc_target_branch">Target branch</label>
                  <input
                    id="gc_target_branch"
                    name="target_branch"
                    type="text"
                    value={gitForm.target_branch}
                    onChange={handleGitChange}
                    placeholder="main"
                  />
                </div>
              </div>

              <div className="form-group">
                <label htmlFor="gc_commit_hash">Commit hash</label>
                <input
                  id="gc_commit_hash"
                  name="commit_hash"
                  type="text"
                  value={gitForm.commit_hash}
                  onChange={handleGitChange}
                  placeholder="abc1234"
                />
              </div>

              <div className="form-group">
                <label htmlFor="gc_pull_request_url">Pull/merge request URL</label>
                <input
                  id="gc_pull_request_url"
                  name="pull_request_url"
                  type="url"
                  value={gitForm.pull_request_url}
                  onChange={handleGitChange}
                  placeholder="https://github.com/org/repo/pull/42 or https://gitlab.com/org/repo/-/merge_requests/7"
                />
              </div>

              <div className="form-group">
                <label htmlFor="gc_changed_files_summary">Changed files summary</label>
                <textarea
                  id="gc_changed_files_summary"
                  name="changed_files_summary"
                  rows="3"
                  value={gitForm.changed_files_summary}
                  onChange={handleGitChange}
                  placeholder="backend/auth.py, frontend/LoginPage.jsx"
                />
              </div>

              <div className="form-group">
                <label htmlFor="gc_diff_text">Diff / change summary</label>
                <textarea
                  id="gc_diff_text"
                  name="diff_text"
                  rows="5"
                  value={gitForm.diff_text}
                  onChange={handleGitChange}
                  placeholder="Briefly describe what changed and why"
                />
              </div>
            </div>
          )}
        </div>

        <div className="page-actions">
          <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating..." : "Create Request"}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => {
              setForm(initialForm);
              setGitForm(initialGitForm);
              setError("");
              setSuccessMessage("");
            }}
          >
            Reset
          </button>
        </div>
      </form>
    </div>
  );
}
