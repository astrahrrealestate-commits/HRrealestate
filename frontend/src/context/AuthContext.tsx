"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/backend";

export interface AuthUser {
  email: string;
  name: string;
  role: string;
  company_id?: string;
  /** Section keys this profile may open (every section for a superadmin). */
  sections: string[];
  isAdmin: boolean;
}

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  /** Whether the signed-in profile may open a section ("admin" = team management). True while nobody is known
   * (local development without a session, or the API offline): the API refuses what is not allowed. */
  canAccess: (section: string) => boolean;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  isAuthenticated: false,
  logout: async () => {},
  refreshUser: async () => {},
  canAccess: () => true,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const fetchCurrentUser = async () => {
    try {
      const res = await apiFetch("/api/auth/me", {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "include",
      });

      if (res.ok) {
        const data = await res.json();
        if (data.authenticated && data.email) {
          if (data.token) {
            localStorage.setItem("eo_session_token", data.token);
          }
          setUser({
            email: data.email,
            name: data.name || data.email.split("@")[0],
            role: data.role || "manager",
            company_id: data.company_id,
            sections: Array.isArray(data.sections) ? data.sections : [],
            isAdmin: data.is_admin === true,
          });
          return;
        }
      }
      setUser(null);
    } catch {
      // Backend offline or network error
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const urlToken = params.get("session_token");
      if (urlToken) {
        localStorage.setItem("eo_session_token", urlToken);
        params.delete("session_token");
        const newSearch = params.toString() ? `?${params.toString()}` : "";
        window.history.replaceState({}, "", `${window.location.pathname}${newSearch}`);
      }
    }
    fetchCurrentUser();
  }, []);

  const logout = async () => {
    try {
      await apiFetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Ignore network errors on logout
    }
    if (typeof window !== "undefined") {
      localStorage.removeItem("eo_session_token");
    }
    // Also clear client cookie if possible
    document.cookie = "eo_session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;";
    setUser(null);
    router.push("/login");
  };

  const canAccess = (section: string) => {
    if (isLoading) return false; // never flash a restricted person's nav while their profile loads
    if (!user) return true;
    if (section === "admin") return user.isAdmin;
    return user.isAdmin || user.sections.includes(section);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        logout,
        refreshUser: fetchCurrentUser,
        canAccess,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
