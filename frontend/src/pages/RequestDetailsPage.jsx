import { Link, useParams } from "react-router-dom";
import { getRequestById } from "../utils/mockRequests";

export default function RequestDetailsPage() {
  const { id } = useParams();
  const request = getRequestById(id);

  if (!request) {
    return (
      <div className="page-card">
        <h2 className="page-title">Request not found</h2>
        <p className="page-subtitle">
          The request you are trying to open does not exist in the current mock
          dataset.
        </p>

        <Link to="/requests" className="btn btn-secondary">
          Back to Requests
        </Link>
      </div>
    );
  }

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">{request.title}</h2>
          <p className="page-subtitle">
            Detailed request view. Later this page can be connected to the real
            backend endpoint by request ID.
          </p>
        </div>

        <Link to="/requests" className="btn btn-secondary">
          Back
        </Link>
      </div>

      <div className="details-grid">
        <div className="detail-box">
          <span className="detail-label">Status</span>
          <strong>{request.status}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Priority</span>
          <strong>{request.priority}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Type</span>
          <strong>{request.type}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Created At</span>
          <strong>{request.createdAt}</strong>
        </div>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">Description</h3>
        <p>{request.description}</p>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">Requester Information</h3>
        <div className="details-grid">
          <div className="detail-box">
            <span className="detail-label">Name</span>
            <strong>{request.creator}</strong>
          </div>

          <div className="detail-box">
            <span className="detail-label">Email</span>
            <strong>{request.creatorEmail}</strong>
          </div>
        </div>
      </div>

      <div className="page-actions">
        <button className="btn btn-primary" type="button">
          Approve
        </button>
        <button className="btn btn-secondary" type="button">
          Request Changes
        </button>
        <button className="btn btn-danger" type="button">
          Reject
        </button>
      </div>
    </div>
  );
}