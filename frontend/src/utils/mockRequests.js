export const mockRequests = [
  {
    id: 1,
    title: "Grant access to production monitoring dashboard",
    description:
      "Need read-only access to the production monitoring dashboard for incident investigation and weekly service health checks.",
    status: "Pending Review",
    priority: "High",
    type: "Access Request",
    creator: "John",
    creatorEmail: "john@test.com",
    createdAt: "2026-03-18",
  },
  {
    id: 2,
    title: "Add junior developer to internal Git repository",
    description:
      "Requesting repository access for a new team member so they can review code, clone the project, and create feature branches.",
    status: "Approved",
    priority: "Medium",
    type: "Repository Access",
    creator: "Alex",
    creatorEmail: "alex@test.com",
    createdAt: "2026-03-17",
  },
  {
    id: 3,
    title: "VPN access for remote troubleshooting",
    description:
      "Temporary VPN access is required for remote debugging and log collection from the internal environment.",
    status: "Changes Requested",
    priority: "High",
    type: "Network Access",
    creator: "Maria",
    creatorEmail: "maria@test.com",
    createdAt: "2026-03-16",
  },
  {
    id: 4,
    title: "Create account for external auditor",
    description:
      "An external auditor needs a time-limited account with restricted permissions for compliance review.",
    status: "Draft",
    priority: "Low",
    type: "User Provisioning",
    creator: "Dmytro",
    creatorEmail: "dmytro@test.com",
    createdAt: "2026-03-15",
  },
];

export function getRequestById(id) {
  return mockRequests.find((request) => String(request.id) === String(id));
}