import { useState } from "react";

const mockUsers = [
  {
    id: 1,
    name: "Admin User",
    email: "admin@test.com",
    role: "admin",
    status: "Active",
  },
  {
    id: 2,
    name: "Team Lead",
    email: "lead@test.com",
    role: "lead",
    status: "Active",
  },
  {
    id: 3,
    name: "Senior Engineer",
    email: "senior@test.com",
    role: "senior",
    status: "Active",
  },
  {
    id: 4,
    name: "Junior Developer",
    email: "junior@test.com",
    role: "junior",
    status: "Pending",
  },
  {
    id: 5,
    name: "Mid Engineer",
    email: "mid@test.com",
    role: "mid",
    status: "Inactive",
  },
];

export default function UserManagementPage() {
  const [search, setSearch] = useState("");

  const filteredUsers = mockUsers.filter((user) => {
    const term = search.toLowerCase();
    return (
      user.name.toLowerCase().includes(term) ||
      user.email.toLowerCase().includes(term) ||
      user.role.toLowerCase().includes(term)
    );
  });

  return (
    <div className="page-card">
      <div className="page-header-row">
        <div>
          <h2 className="page-title">User Management</h2>
          <p className="page-subtitle">
            Manage users, roles, and account states. This version uses mock data
            for navigation and UI testing.
          </p>
        </div>

        <button type="button" className="btn btn-primary">
          Add User
        </button>
      </div>

      <div className="toolbar-row">
        <div className="toolbar-search">
          <input
            type="text"
            placeholder="Search by name, email, or role"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="toolbar-stats">
          <span className="request-chip">{filteredUsers.length} visible</span>
        </div>
      </div>

      <div className="users-table-wrapper">
        <table className="users-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th className="actions-col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map((user) => (
              <tr key={user.id}>
                <td>
                  <div className="user-cell">
                    <div className="user-avatar">
                      {user.name.charAt(0).toUpperCase()}
                    </div>
                    <span>{user.name}</span>
                  </div>
                </td>
                <td>{user.email}</td>
                <td>
                  <span className="role-pill">{user.role}</span>
                </td>
                <td>
                  <span className={`status-badge status-${user.status.toLowerCase()}`}>
                    {user.status}
                  </span>
                </td>
                <td className="actions-col">
                  <div className="table-actions">
                    <button type="button" className="btn btn-secondary btn-sm">
                      Edit
                    </button>
                    <button type="button" className="btn btn-secondary btn-sm">
                      Role
                    </button>
                    <button type="button" className="btn btn-danger btn-sm">
                      Disable
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filteredUsers.length === 0 && (
          <div className="empty-state user-empty-state">
            No users matched your search.
          </div>
        )}
      </div>
    </div>
  );
}