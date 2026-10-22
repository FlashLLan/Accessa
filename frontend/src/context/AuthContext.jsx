import { useCallback, useEffect, useMemo, useState } from "react";
import { getMe } from "../api/users";
import { setLastWorkspaceSlug } from "../utils/storage";
import { AuthContext } from "./authContextObject";

function normalizeUser(rawUser) {
  if (!rawUser) return null;

  // Remember the workspace so logout and "/" can return to its login page.
  setLastWorkspaceSlug(rawUser.workspace?.slug);

  return {
    ...rawUser,
    name: rawUser.name ?? rawUser.full_name ?? "",
    role:
      typeof rawUser.role === "string"
        ? rawUser.role
        : rawUser.role?.name ?? "",
  };
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
    setAuthLoading(false);
  }, []);

  const fetchMe = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(normalizeUser(me));
    } catch (error) {
      console.error("Failed to fetch current user", error);
      logout();
    } finally {
      setAuthLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setAuthLoading(false);
      return;
    }

    setAuthLoading(true);
    fetchMe();
  }, [token, fetchMe]);

  const login = useCallback(
    async (newToken) => {
      localStorage.setItem("token", newToken);
      setToken(newToken);
      setAuthLoading(true);

      try {
        const me = await getMe();
        setUser(normalizeUser(me));
      } catch (error) {
        console.error("Failed to fetch current user after login", error);
        logout();
        throw error;
      } finally {
        setAuthLoading(false);
      }
    },
    [logout]
  );

  const value = useMemo(
    () => ({
      token,
      user,
      authLoading,
      isAuthenticated: Boolean(token && user),
      login,
      logout,
      refreshMe: fetchMe,
    }),
    [token, user, authLoading, login, logout, fetchMe]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}