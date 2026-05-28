import {
  addChangeRequestComment,
  applyChangeRequest,
  approveChangeRequest,
  createChangeRequest,
  delegateChangeRequest,
  escalateChangeRequest,
  getChangeRequestApprovals,
  getChangeRequestById,
  getChangeRequestComments,
  getChangeRequests,
  getReviewActions,
  rejectChangeRequest,
  submitChangeRequest,
} from "../api/changeRequests";

export const requestService = {
  async list() {
    return getChangeRequests();
  },

  async getById(id) {
    return getChangeRequestById(id);
  },

  async create(payload) {
    return createChangeRequest(payload);
  },

  async submit(id) {
    return submitChangeRequest(id);
  },

  async approve(id, decisionComment = "") {
    return approveChangeRequest(id, decisionComment);
  },

  async reject(id, decisionComment = "") {
    return rejectChangeRequest(id, decisionComment);
  },

  async listApprovals(id) {
    return getChangeRequestApprovals(id);
  },

  async listComments(id) {
    return getChangeRequestComments(id);
  },

  async addComment(id, commentText) {
    return addChangeRequestComment(id, commentText);
  },

  async apply(id) {
    return applyChangeRequest(id);
  },

  async escalate(id, targetReviewerId, comment = "") {
    return escalateChangeRequest(id, targetReviewerId, comment);
  },

  async delegate(id, targetReviewerId, comment = "") {
    return delegateChangeRequest(id, targetReviewerId, comment);
  },

  async listReviewActions(id) {
    return getReviewActions(id);
  },
};