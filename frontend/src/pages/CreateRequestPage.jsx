import { useState } from "react";

const initialForm = {
  title: "",
  type: "Access Request",
  priority: "Medium",
  description: "",
};

export default function CreateRequestPage() {
  const [form, setForm] = useState(initialForm);
  const [submitted, setSubmitted] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;

    setForm((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();

    console.log("Mock request submitted:", form);
    setSubmitted(true);

    setForm(initialForm);
  };

  return (
    <div className="page-card">
      <h2 className="page-title">Create Request</h2>
      <p className="page-subtitle">
        Submit a new request through a simple form. For now this only simulates
        submission and logs the payload in the browser console.
      </p>

      {submitted && (
        <div className="success-banner">
          Mock request submitted successfully. Check the browser console.
        </div>
      )}

      <form className="request-form" onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="title">Request Title</label>
          <input
            id="title"
            name="title"
            type="text"
            value={form.title}
            onChange={handleChange}
            placeholder="Enter a clear request title"
            required
          />
        </div>

        <div className="form-row">
          <div className="form-group">
            <label htmlFor="type">Request Type</label>
            <select
              id="type"
              name="type"
              value={form.type}
              onChange={handleChange}
            >
              <option>Access Request</option>
              <option>Repository Access</option>
              <option>Network Access</option>
              <option>User Provisioning</option>
              <option>Permission Change</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="priority">Priority</label>
            <select
              id="priority"
              name="priority"
              value={form.priority}
              onChange={handleChange}
            >
              <option>Low</option>
              <option>Medium</option>
              <option>High</option>
            </select>
          </div>
        </div>

        <div className="form-group">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            name="description"
            rows="7"
            value={form.description}
            onChange={handleChange}
            placeholder="Describe the reason, scope, and any important details"
            required
          />
        </div>

        <div className="page-actions">
          <button className="btn btn-primary" type="submit">
            Submit Request
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            onClick={() => {
              setForm(initialForm);
              setSubmitted(false);
            }}
          >
            Reset
          </button>
        </div>
      </form>
    </div>
  );
}