import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { requestService } from "../services/requestsService.js";
import { useAuth } from "../hooks/useAuth";
import { canReviewRequest } from "../utils/requestPermissions";
import { extractApiError } from "../utils/apiError";
import {
  formatDateTime,
  formatEnumLabel,
  getStatusBadgeClass,
} from "../utils/requestPresentation";

export default function ReviewPage() {
  const { user } = useAuth();

  const [requests, setRequests] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

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
                </div>
              </div>

              {/* Decisions are made on the request page, after the Git context,
                  diff and AI review have been seen. */}
              <div className="review-actions">
                <Link to={`/requests/${request.id}`} className="btn btn-primary">
                  Open
                </Link>
                <span className="request-date">
                  {formatDateTime(request.created_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

