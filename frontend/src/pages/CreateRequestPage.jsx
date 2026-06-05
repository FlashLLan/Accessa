import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Toast from "../components/common/Toast";
import { requestService } from "../services/requestsService.js";
import { getReviewers } from "../api/users";
import { useAuth } from "../hooks/useAuth";

const initialForm = {
  title: "",
  description: "",
  request_type: "access_change",
  target_system: "",
  environment: "dev",
  risk_level: "medium",
  assigned_reviewer_id: "",
};

export default function CreateRequestPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [form, setForm] = useState(initialForm);
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
          err?.response?.data?.detail ||
            "Failed to load reviewers. Please try again."
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
      // Clear the reviewer selection when risk level changes — the eligible list will update
      ...(name === "risk_level" ? { assigned_reviewer_id: "" } : {}),
    }));
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

      const created = await requestService.create(payload);

      setSuccessMessage("Request created successfully.");
      setForm(initialForm);

      setTimeout(() => {
        navigate(`/requests/${created.id}`);
      }, 600);
    } catch (err) {
      console.error("Failed to create request", err);
      setToastError(
        err?.response?.data?.detail ||
          "Failed to create the request. Please check your input."
      );
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
              <option value="dev">Dev</option>
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

        <div className="page-actions">
          <button className="btn btn-primary" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating..." : "Create Request"}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => {
              setForm(initialForm);
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