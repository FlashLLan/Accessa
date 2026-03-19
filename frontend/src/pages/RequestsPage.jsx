import { Link } from "react-router-dom";
import { mockRequests } from "../utils/mockRequests";

export default function RequestsPage() {
  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">Requests</h2>
          <p className="page-subtitle">
            Browse submitted requests, track their status, and open a specific
            request for more details.
          </p>
        </div>

        <Link to="/requests/new" className="btn btn-primary">
          New Request
        </Link>
      </div>

      <div className="request-list">
        {mockRequests.map((request) => (
          <Link
            key={request.id}
            to={`/requests/${request.id}`}
            className="request-card"
          >
            <div className="request-card-top">
              <div>
                <h3 className="request-card-title">{request.title}</h3>
                <p className="request-card-meta">
                  {request.type} • Created by {request.creator}
                </p>
              </div>

              <span className={`status-badge status-${slugify(request.status)}`}>
                {request.status}
              </span>
            </div>

            <p className="request-card-description">{request.description}</p>

            <div className="request-card-bottom">
              <span className="request-chip">{request.priority} Priority</span>
              <span className="request-date">{request.createdAt}</span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function slugify(value) {
  return value.toLowerCase().replace(/\s+/g, "-");
}