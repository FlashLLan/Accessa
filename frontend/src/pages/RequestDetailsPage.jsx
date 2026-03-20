import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { requestService } from "../services/requestsService.js";
import { useAuth } from "../hooks/useAuth";

export default function RequestDetailsPage() {
  const { id } = useParams();
  const { user } = useAuth();

  const [request, setRequest] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [comments, setComments] = useState([]);
  const [commentText, setCommentText] = useState("");
  const [decisionComment, setDecisionComment] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    loadAll();
  }, [id]);

  async function loadAll() {
    try {
      setIsLoading(true);
      setError("");

      const [requestData, approvalsData, commentsData] = await Promise.all([
        requestService.getById(id),
        requestService.listApprovals(id).catch(() => []),
        requestService.listComments(id).catch(() => []),
      ]);

      setRequest(requestData);
      setApprovals(approvalsData);
      setComments(commentsData);
    } catch (err) {
      console.error("Failed to load request", err);
      setError(
        err?.response?.data?.detail ||
          "Failed to load request. Please try again."
      );
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmitForReview() {
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      const updated = await requestService.submit(id);
      setRequest(updated);
      setActionMessage("Request submitted for review.");
    } catch (err) {
      console.error("Failed to submit request", err);
      setError(
        err?.response?.data?.detail ||
          "Failed to submit the request for review."
      );
    } finally {
      setActionLoading(false);
    }
  }

  async function handleApprove() {
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      const updated = await requestService.approve(id, decisionComment);
      setRequest(updated);
      setDecisionComment("");
      setActionMessage("Request approved.");
      await loadAll();
    } catch (err) {
      console.error("Failed to approve request", err);
      setError(
        err?.response?.data?.detail || "Failed to approve the request."
      );
    } finally {
      setActionLoading(false);
    }
  }

  async function handleReject() {
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      const updated = await requestService.reject(id, decisionComment);
      setRequest(updated);
      setDecisionComment("");
      setActionMessage("Request rejected.");
      await loadAll();
    } catch (err) {
      console.error("Failed to reject request", err);
      setError(
        err?.response?.data?.detail || "Failed to reject the request."
      );
    } finally {
      setActionLoading(false);
    }
  }

  async function handleApply() {
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      const updated = await requestService.apply(id);
      setRequest(updated);
      setActionMessage("Request marked as applied.");
    } catch (err) {
      console.error("Failed to apply request", err);
      setError(
        err?.response?.data?.detail ||
          "Failed to mark the request as applied."
      );
    } finally {
      setActionLoading(false);
    }
  }

  async function handleAddComment(e) {
    e.preventDefault();

    if (!commentText.trim()) return;

    try {
      setActionLoading(true);
      setError("");
      await requestService.addComment(id, commentText.trim());
      setCommentText("");
      await loadAll();
    } catch (err) {
      console.error("Failed to add comment", err);
      setError(
        err?.response?.data?.detail || "Failed to add the comment."
      );
    } finally {
      setActionLoading(false);
    }
  }

  if (isLoading) {
    return (
      <div className="page-card">
        <div className="empty-state">Loading request...</div>
      </div>
    );
  }

  if (error && !request) {
    return (
      <div className="page-card">
        <h2 className="page-title">Request Details</h2>
        <div className="auth-error">{error}</div>
        <Link to="/requests" className="btn btn-secondary">
          Back to Requests
        </Link>
      </div>
    );
  }

  const isAdmin = user?.role === "admin";
  const isCreator =
    user?.email &&
    request?.creator?.email &&
    user.email.toLowerCase() === request.creator.email.toLowerCase();

  const isAssignedReviewer =
    user?.email &&
    request?.assigned_reviewer?.email &&
    user.email.toLowerCase() === request.assigned_reviewer.email.toLowerCase();

  const canSubmit =
    isCreator &&
    (request?.status === "draft" || request?.status === "rejected");

  const canReview =
    (isAdmin || isAssignedReviewer) &&
    !isCreator &&
    request?.status === "pending_review";

  const canApply =
    request?.status === "approved" && (isCreator || isAdmin);

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">{request.title}</h2>
          <p className="page-subtitle">
            Real request details with comments and approval history.
          </p>
        </div>

        <Link to="/requests" className="btn btn-secondary">
          Back
        </Link>
      </div>

      {error && <div className="auth-error">{error}</div>}
      {actionMessage && <div className="success-banner">{actionMessage}</div>}

      <div className="details-grid">
        <div className="detail-box">
          <span className="detail-label">Status</span>
          <strong>{formatEnumLabel(request.status)}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Risk Level</span>
          <strong>{formatEnumLabel(request.risk_level)}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Request Type</span>
          <strong>{formatEnumLabel(request.request_type)}</strong>
        </div>

        <div className="detail-box">
          <span className="detail-label">Environment</span>
          <strong>{formatEnumLabel(request.environment)}</strong>
        </div>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">Description</h3>
        <p>{request.description}</p>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">Target Information</h3>
        <div className="details-grid">
          <div className="detail-box">
            <span className="detail-label">Target System</span>
            <strong>{request.target_system}</strong>
          </div>

          <div className="detail-box">
            <span className="detail-label">Created At</span>
            <strong>{formatDate(request.created_at)}</strong>
          </div>
        </div>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">People</h3>
        <div className="details-grid">
          <div className="detail-box">
            <span className="detail-label">Creator</span>
            <strong>{request.creator?.full_name || request.creator?.email}</strong>
          </div>

          <div className="detail-box">
            <span className="detail-label">Assigned Reviewer</span>
            <strong>
              {request.assigned_reviewer?.full_name ||
                request.assigned_reviewer?.email}
            </strong>
          </div>
        </div>
      </div>

      {(canReview || canSubmit || canApply) && (
        <div className="details-section">
          <h3 className="details-section-title">Actions</h3>

          {canReview && (
            <div className="form-group action-comment-box">
              <label htmlFor="decisionComment">Decision comment</label>
              <textarea
                id="decisionComment"
                rows="3"
                placeholder="Optional note for approval or rejection"
                value={decisionComment}
                onChange={(e) => setDecisionComment(e.target.value)}
              />
            </div>
          )}

          <div className="page-actions">
            {canSubmit && (
              <button
                className="btn btn-primary"
                type="button"
                onClick={handleSubmitForReview}
                disabled={actionLoading}
              >
                {actionLoading ? "Working..." : "Submit for Review"}
              </button>
            )}

            {canReview && (
              <>
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={handleApprove}
                  disabled={actionLoading}
                >
                  {actionLoading ? "Working..." : "Approve"}
                </button>
                <button
                  className="btn btn-danger"
                  type="button"
                  onClick={handleReject}
                  disabled={actionLoading}
                >
                  {actionLoading ? "Working..." : "Reject"}
                </button>
              </>
            )}

            {canApply && (
              <button
                className="btn btn-primary"
                type="button"
                onClick={handleApply}
                disabled={actionLoading}
              >
                {actionLoading ? "Working..." : "Mark as Applied"}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="details-section">
        <h3 className="details-section-title">Comments</h3>

        <form className="comment-form" onSubmit={handleAddComment}>
          <div className="form-group">
            <label htmlFor="commentText">Add comment</label>
            <textarea
              id="commentText"
              rows="3"
              placeholder="Write a comment"
              value={commentText}
              onChange={(e) => setCommentText(e.target.value)}
            />
          </div>

          <div className="page-actions">
            <button className="btn btn-secondary" type="submit" disabled={actionLoading}>
              {actionLoading ? "Working..." : "Add Comment"}
            </button>
          </div>
        </form>

        <div className="timeline-list">
          {comments.length === 0 ? (
            <div className="empty-state">No comments yet.</div>
          ) : (
            comments.map((comment) => (
              <div key={comment.id} className="timeline-card">
                <div className="timeline-card-top">
                  <strong>{comment.user?.full_name || comment.user?.email}</strong>
                  <span className="request-date">{formatDate(comment.created_at)}</span>
                </div>
                <p>{comment.comment_text}</p>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="details-section">
        <h3 className="details-section-title">Approval History</h3>

        <div className="timeline-list">
          {approvals.length === 0 ? (
            <div className="empty-state">No approval decisions yet.</div>
          ) : (
            approvals.map((approval) => (
              <div key={approval.id} className="timeline-card">
                <div className="timeline-card-top">
                  <strong>{approval.reviewer?.full_name || approval.reviewer?.email}</strong>
                  <span
                    className={`status-badge status-${String(
                      approval.decision || ""
                    ).toLowerCase()}`}
                  >
                    {formatEnumLabel(approval.decision)}
                  </span>
                </div>
                <p>{approval.decision_comment || "No comment provided."}</p>
                <span className="request-date">{formatDate(approval.created_at)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function formatEnumLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatDate(value) {
  return new Date(value).toLocaleString();
}