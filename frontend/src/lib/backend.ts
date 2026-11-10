/**
 * The one way the SPA talks to the EstateOS API.
 *
 * `apiFetch` always sends the session cookie (`credentials: "include"`) and, for anything that changes state, the
 * `X-EstateOS-Client` header the API requires as its third CSRF layer. Never call `fetch` on the backend directly: a
 * bare `fetch` sends no cookie, so every dashboard route answers 401 outside local development.
 */

export const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function backendUrl(pathOrUrl: string): string {
  if (typeof window !== "undefined") {
    // Client-side: normalize to relative URL to use Next.js same-origin rewrite proxy
    if (pathOrUrl.startsWith("http://localhost:8000")) {
      return pathOrUrl.replace("http://localhost:8000", "");
    }
    if (pathOrUrl.startsWith("http://127.0.0.1:8000")) {
      return pathOrUrl.replace("http://127.0.0.1:8000", "");
    }
    if (!pathOrUrl.startsWith("http")) {
      return pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
    }
  }
  return pathOrUrl.startsWith("http") ? pathOrUrl : `${BACKEND_BASE_URL}${pathOrUrl}`;
}

export function apiFetch(pathOrUrl: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method)) headers.set("X-EstateOS-Client", "dashboard");

  if (typeof window !== "undefined") {
    const token = localStorage.getItem("eo_session_token");
    if (token && !headers.has("X-Session-Token")) {
      headers.set("X-Session-Token", token);
    }
  }

  return fetch(backendUrl(pathOrUrl), { ...init, headers, credentials: "include" });
}
