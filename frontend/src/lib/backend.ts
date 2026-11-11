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
  return pathOrUrl.startsWith("http") ? pathOrUrl : `${BACKEND_BASE_URL}${pathOrUrl}`;
}

export function apiFetch(pathOrUrl: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method)) headers.set("X-EstateOS-Client", "dashboard");
  return fetch(backendUrl(pathOrUrl), { ...init, headers, credentials: "include" });
}
