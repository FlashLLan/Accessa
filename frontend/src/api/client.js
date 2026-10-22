import axios from "axios";
import { isMfaSetupRequired, isPasswordChangeRequired } from "../utils/apiError";

const client = axios.create({
  baseURL: "http://localhost:8000", // change if needed
});

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  // A request that already names its token (the MFA code step) keeps it.
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// The backend blocks every endpoint except "my profile" and "change my password"
// until an admin-set initial password is changed, and then everything except MFA
// enrolment until MFA is set up. Send the user to the matching page.
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isPasswordChangeRequired(error) && window.location.pathname !== "/change-password") {
      window.location.assign("/change-password");
    } else if (isMfaSetupRequired(error) && window.location.pathname !== "/mfa-setup") {
      window.location.assign("/mfa-setup");
    }
    return Promise.reject(error);
  }
);

export default client;