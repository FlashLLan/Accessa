import axios from "axios";
import { isPasswordChangeRequired } from "../utils/apiError";

const client = axios.create({
  baseURL: "http://localhost:8000", // change if needed
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// The backend blocks every endpoint except "my profile" and "change my password"
// until an admin-set initial password is changed. Send the user to that page.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isPasswordChangeRequired(error) && window.location.pathname !== "/change-password") {
      window.location.assign("/change-password");
    }
    return Promise.reject(error);
  }
);

export default client;