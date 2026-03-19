import { Link } from "react-router-dom";
import { mockRequests } from "../utils/mockRequests";
import { useAuth } from "../hooks/useAuth";

const reviewableRoles = ["admin", "lead", "senior"];
const reviewableStatuses = ["Pending Review", "Changes Requested"];

export default function ReviewPage() {
  const { user } = useAuth();

  const canReview = reviewableRoles.includes(user?.role);
  const reviewQueue = mockRequests.filter((request) =>
    reviewableStatuses.includes(request.status)
  );

  if (!canReview) {
    return (
      <div className="page-card">
        <h2 className="page-title">Review Queue</h2>
        <p className="page-subtitle">
          You do not currently have permission to review requests.
        </p>

        <div className="empty-state">
          This area is reserved for admins, leads, and seniors.
        </div>
      </div>
    );
  }

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Review Queue</h2>
          <p className="page-subtitle">
            Review incoming requests that are waiting for approval or require
            additional clarification.
          </p>
        </div>

        <div className="review-summary-badge">
          {reviewQueue.length} open
        </div>
      </div>

      {reviewQueue.length === 0 ? (
        <div className="empty-state">
          No requests are currently waiting for review.
        </div>
      ) : (
        <div className="review-list">
          {reviewQueue.map((request) => (
            <div key={request.id} className="review-card">
              <div className="review-card-main">
                <div className="review-card-top">
                  <div>
                    <h3 className="request-card-title">{request.title}</h3>
                    <p className="request-card-meta">
                      {request.type} • Created by {request.creator}
                    </p>
                  </div>

                  <span
                    className={`status-badge status-${slugify(request.status)}`}
                  >
                    {request.status}
                  </span>
                </div>

                <p className="request-card-description">{request.description}</p>

                <div className="review-meta-row">
                  <span className="request-chip">{request.priority} Priority</span>
                  <span className="request-date">{request.createdAt}</span>
                </div>
              </div>

              <div className="review-actions">
                <Link to={`/requests/${request.id}`} className="btn btn-secondary">
                  Open
                </Link>
                <button type="button" className="btn btn-primary">
                  Approve
                </button>
                <button type="button" className="btn btn-secondary">
                  Request Changes
                </button>
                <button type="button" className="btn btn-danger">
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function slugify(value) {
  return value.toLowerCase().replace(/\s+/g, "-");
}