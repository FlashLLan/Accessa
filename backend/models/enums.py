import enum


class RoleName(str, enum.Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    ADMIN = "admin"


class RequestType(str, enum.Enum):
    ACCESS_CHANGE = "access_change"
    CONFIGURATION_CHANGE = "configuration_change"
    DEPLOYMENT_CHANGE = "deployment_change"
    RESOURCE_CHANGE = "resource_change"


class EnvironmentType(str, enum.Enum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RequestStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ESCALATED = "escalated"
    DELEGATED = "delegated"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewActionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DELEGATE = "delegate"
    ESCALATE = "escalate"
    COMMENT = "comment"
    ASSIGN = "assign"
    RETURN_FOR_CHANGES = "return_for_changes"