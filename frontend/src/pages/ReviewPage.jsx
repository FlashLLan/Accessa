import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Toast from "../components/common/Toast";
import { requestService } from "../services/requestsService.js";
import { useAuth } from "../hooks/useAuth";
import { canReviewRequest } from "../utils/requestPermissions";
import { extractApiError } from "../utils/apiError";
import {
  formatDate,
  formatEnumLabel,
  getStatusBadgeClass,
} from "../utils/requestPresentation";

export default function ReviewPage() {
  const { user, refreshMe } = useAuth();

  const [requests, setRequests] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [toastError, setToastError] = useState("");
  const [decisionComment, setDecisionComment] = useState({});
  const [actionLoadingId, setActionLoadingId] = useState(null);

  useEffect(() => {
    loadRequests();
  }, []);

  async function loadRequests() {
    try {
      setIsLoading(true);
      setError("");
      const data = await requestService.list();

      const reviewable = data.filter((request) => canReviewRequest(user, request));

      setRequests(reviewable);
    } catch (err) {
      console.error("Failed to load review queue", err);
      setError(
        extractApiError(err, "Failed to load review queue. Please try again.")
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleApprove(id) {
    try {
      setActionLoadingId(id);
      setError("");
      await requestService.approve(id, decisionComment[id] || "");
      await Promise.all([loadRequests(), refreshMe()]);
    } catch (err) {
      console.error("Approve failed", err);
      setToastError(
        extractApiError(err, "Failed to approve the request.")
      );
    } finally {
      setActionLoadingId(null);
    }
  }

  async function handleReject(id) {
    try {
      setActionLoadingId(id);
      setError("");
      await requestService.reject(id, decisionComment[id] || "");
      await Promise.all([loadRequests(), refreshMe()]);
    } catch (err) {
      console.error("Reject failed", err);
      setToastError(
        extractApiError(err, "Failed to reject the request.")
      );
    } finally {
      setActionLoadingId(null);
    }
  }

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Review Queue</h2>
          <p className="page-subtitle">
            Requests assigned to you that are waiting for review.
          </p>
        </div>

        <div className="review-summary-badge">{requests.length} open</div>
      </div>

      {isLoading && <div className="empty-state">Loading review queue...</div>}
      {error && <div className="auth-error">{error}</div>}

      {!isLoading && !error && requests.length === 0 && (
        <div className="empty-state">No requests are waiting for your review.</div>
      )}

      {!isLoading && !error && requests.length > 0 && (
        <div className="review-list">
          {requests.map((request) => (
            <div key={request.id} className="review-card">
              <div className="review-card-main">
                <div className="review-card-top">
                  <div>
                    <h3 className="request-card-title">{request.title}</h3>
                    <p className="request-card-meta">
                      {formatEnumLabel(request.request_type)} • Created by{" "}
                      {request.creator?.full_name || request.creator?.email || "Unknown"}
                    </p>
                  </div>

                  <span className={getStatusBadgeClass(request.status)}>
                    {formatEnumLabel(request.status)}
                  </span>
                </div>

                <p className="request-card-description">{request.description}</p>

                <div className="review-meta-row">
                  <span className="request-chip">
                    {formatEnumLabel(request.risk_level)} Risk
                  </span>
                  <span className="request-date">
                    {formatDate(request.created_at)}
                  </span>
                </div>

                <div className="form-group review-comment-box">
                  <label htmlFor={`decision-${request.id}`}>
                    Decision comment
                  </label>
                  <textarea
                    id={`decision-${request.id}`}
                    rows="3"
                    placeholder="Optional approval/rejection note"
                    value={decisionComment[request.id] || ""}
                    onChange={(e) =>
                      setDecisionComment((prev) => ({
                        ...prev,
                        [request.id]: e.target.value,
                      }))
                    }
                  />
                </div>
              </div>

              <div className="review-actions">
                <Link to={`/requests/${request.id}`} className="btn btn-secondary">
                  Open
                </Link>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => handleApprove(request.id)}
                  disabled={actionLoadingId === request.id}
                >
                  {actionLoadingId === request.id ? "Working..." : "Approve"}
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => handleReject(request.id)}
                  disabled={actionLoadingId === request.id}
                >
                  {actionLoadingId === request.id ? "Working..." : "Reject"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      <Toast message={toastError} type="error" onClose={() => setToastError("")} />
    </div>
  );
}

