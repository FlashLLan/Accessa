import { createContext } from "react";

// Kept apart from AuthProvider so AuthContext.jsx exports only a component
// (needed for React fast refresh).
export const AuthContext = createContext(null);
