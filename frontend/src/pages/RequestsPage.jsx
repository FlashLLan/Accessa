import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { requestService } from "../services/requestsService.js";
import { extractApiError } from "../utils/apiError";
import {
  formatDate,
  formatEnumLabel,
  getStatusBadgeClass,
} from "../utils/requestPresentation";
export default function RequestsPage() {
  const location = useLocation();
  const [requests, setRequests] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const flashMessage = location.state?.message || "";

  useEffect(() => {
    async function loadRequests() {
      try {
        setIsLoading(true);
        setError("");
        const data = await requestService.list();
        setRequests(data);
      } catch (err) {
        console.error("Failed to load requests", err);
        setError(
          extractApiError(err, "Failed to load requests. Please try again.")
        );
      } finally {
        setIsLoading(false);
      }
    }

    loadRequests();
  }, []);

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Requests</h2>
          <p className="page-subtitle">
            Browse your change requests and the requests assigned to you for review.
          </p>
        </div>

        <Link to="/requests/new" className="btn btn-primary">
          New Request
        </Link>
      </div>

      {flashMessage && <div className="success-banner">{flashMessage}</div>}

      {isLoading && <div className="empty-state">Loading requests...</div>}

      {error && <div className="auth-error">{error}</div>}

      {!isLoading && !error && requests.length === 0 && (
        <div className="empty-state">No requests found yet.</div>
      )}

      {!isLoading && !error && requests.length > 0 && (
        <div className="request-list">
          {requests.map((request) => (
            <Link
              key={request.id}
              to={`/requests/${request.id}`}
              className="request-card"
            >
              <div className="request-card-top">
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

              <div className="request-card-bottom">
                <span className="request-chip">
                  {formatEnumLabel(request.risk_level)} Risk
                </span>
                <span className="request-date">
                  {formatDate(request.created_at)}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

