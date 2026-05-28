import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { requestService } from "../services/requestsService.js";
import { getReviewers } from "../api/users.js";
import { useAuth } from "../hooks/useAuth";
import {
  canApplyRequest,
  canApproveRequest,
  canDelegateRequest,
  canEscalateRequest,
  canRejectRequest,
  canSubmitRequest,
  canViewRequestComments,
} from "../utils/requestPermissions";
import {
  formatDate,
  formatEnumLabel,
  getStatusBadgeClass,
  getDecisionBadgeClass,
} from "../utils/requestPresentation";

export default function RequestDetailsPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [request, setRequest] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [comments, setComments] = useState([]);
  const [reviewActions, setReviewActions] = useState([]);
  const [availableReviewers, setAvailableReviewers] = useState([]);
  const [commentText, setCommentText] = useState("");
  const [decisionComment, setDecisionComment] = useState("");
  const [transferComment, setTransferComment] = useState("");
  const [selectedReviewerId, setSelectedReviewerId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [actionLoading, setActionLoading] = useState(false);
  const canViewComments = canViewRequestComments(user, request);

  useEffect(() => {
    loadAll();
  }, [id]);

  async function loadAll() {
    try {
      setIsLoading(true);
      setError("");

      const [requestData, approvalsData, commentsData, reviewActionsData] = await Promise.all([
        requestService.getById(id),
        requestService.listApprovals(id).catch(() => []),
        requestService.listComments(id).catch(() => []),
        requestService.listReviewActions(id).catch(() => []),
      ]);

      setRequest(requestData);
      setApprovals(approvalsData);
      setComments(commentsData);
      setReviewActions(reviewActionsData);

      if (requestData?.status === "pending_review") {
        const reviewers = await getReviewers(
          requestData.creator?.role?.name,
          requestData.risk_level,
        ).catch(() => []);
        const pastActorIds = reviewActionsData.map(a => a.actor?.id).filter(Boolean);
        const excluded = new Set([
          requestData.assigned_reviewer?.id,
          requestData.current_reviewer?.id,
          ...pastActorIds,
        ].filter(Boolean));
        setAvailableReviewers(reviewers.filter(r => !excluded.has(r.id)));
      }
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

  async function handleEscalate() {
    if (!selectedReviewerId) {
      setError("Please select a target reviewer before escalating.");
      return;
    }
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      await requestService.escalate(id, parseInt(selectedReviewerId), transferComment);
      navigate("/requests", { state: { message: "Request escalated." } });
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to escalate the request.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleDelegate() {
    if (!selectedReviewerId) {
      setError("Please select a target reviewer before delegating.");
      return;
    }
    try {
      setActionLoading(true);
      setError("");
      setActionMessage("");
      await requestService.delegate(id, parseInt(selectedReviewerId), transferComment);
      navigate("/requests", { state: { message: "Request delegated." } });
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to delegate the request.");
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

const canSubmit = canSubmitRequest(user, request);
const canApprove = canApproveRequest(user, request);
const canReject = canRejectRequest(user, request);
const canApply = canApplyRequest(user, request);
const canEscalate = canEscalateRequest(user, request);
const canDelegate = canDelegateRequest(user, request);
const canReview = canApprove || canReject;
const canTransfer = canEscalate || canDelegate;

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
          <span className={getStatusBadgeClass(request.status)}>
                {formatEnumLabel(request.status)}
            </span>
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

      {canTransfer && (
        <div className="details-section">
          <h3 className="details-section-title">Escalate / Delegate</h3>

          <div className="form-group" style={{ marginBottom: "14px" }}>
            <label htmlFor="targetReviewer">Target reviewer</label>
            <select
              id="targetReviewer"
              value={selectedReviewerId}
              onChange={(e) => setSelectedReviewerId(e.target.value)}
            >
              <option value="">— Select reviewer —</option>
              {availableReviewers.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.full_name || r.email} ({r.role?.name ?? "unknown"})
                </option>
              ))}
            </select>
          </div>

          <div className="form-group action-comment-box" style={{ marginBottom: "14px" }}>
            <label htmlFor="transferComment">Comment (optional)</label>
            <textarea
              id="transferComment"
              rows="2"
              placeholder="Reason for escalating or delegating"
              value={transferComment}
              onChange={(e) => setTransferComment(e.target.value)}
            />
          </div>

          <div className="page-actions">
            {canEscalate && (
              <button
                className="btn btn-warning"
                type="button"
                onClick={handleEscalate}
                disabled={actionLoading}
              >
                {actionLoading ? "Working..." : "Escalate"}
              </button>
            )}
            {canDelegate && (
              <button
                className="btn btn-secondary"
                type="button"
                onClick={handleDelegate}
                disabled={actionLoading}
              >
                {actionLoading ? "Working..." : "Delegate"}
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
                  <span className={getDecisionBadgeClass(approval.decision)}>
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

      {reviewActions.length > 0 && (
        <div className="details-section">
          <h3 className="details-section-title">Review Action History</h3>

          <div className="timeline-list">
            {reviewActions.map((action) => (
              <div key={action.id} className="timeline-card">
                <div className="timeline-card-top">
                  <strong>{action.actor?.full_name || action.actor?.email}</strong>
                  <span className="status-badge status-delegated">
                    {formatEnumLabel(action.action_type)}
                  </span>
                </div>
                {action.target_reviewer && (
                  <p style={{ marginBottom: "4px" }}>
                    → {action.target_reviewer.full_name || action.target_reviewer.email}
                  </p>
                )}
                {action.comment && <p>{action.comment}</p>}
                <span className="request-date">{formatDate(action.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

