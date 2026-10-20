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
    CODE_CHANGE = "code_change"
    SECURITY_CHANGE = "security_change"
    ADMINISTRATIVE_CHANGE = "administrative_change"
    DEPLOYMENT_CHANGE = "deployment_change"
    RESOURCE_CHANGE = "resource_change"


class EnvironmentType(str, enum.Enum):
    DEV = "development"
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


class ApprovalDecision(str, enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewActionType(str, enum.Enum):
    # Escalation and delegation are the only review actions recorded here;
    # approvals and comments have their own tables.
    DELEGATE = "delegate"
    ESCALATE = "escalate"
