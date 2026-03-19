export function buildMockUser(email) {
  const normalizedEmail = email.trim().toLowerCase();

  const usersMap = {
    "admin@test.com": {
      id: 1,
      name: "Admin User",
      email: "admin@test.com",
      role: "admin",
    },
    "lead@test.com": {
      id: 2,
      name: "Lead User",
      email: "lead@test.com",
      role: "lead",
    },
    "senior@test.com": {
      id: 3,
      name: "Senior User",
      email: "senior@test.com",
      role: "senior",
    },
    "mid@test.com": {
      id: 4,
      name: "Mid User",
      email: "mid@test.com",
      role: "mid",
    },
    "junior@test.com": {
      id: 5,
      name: "Junior User",
      email: "junior@test.com",
      role: "junior",
    },
  };

  return (
    usersMap[normalizedEmail] || {
      id: 999,
      name: "Unknown User",
      email: normalizedEmail,
      role: "junior",
    }
  );
}