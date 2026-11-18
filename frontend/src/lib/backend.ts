/**
 * The one way the SPA talks to the EstateOS API.
 *
 * `apiFetch` always sends the session cookie (`credentials: "include"`) and, for anything that changes state, the
 * `X-EstateOS-Client` header the API requires as its third CSRF layer. Never call `fetch` on the backend directly: a
 * bare `fetch` sends no cookie, so every dashboard route answers 401 outside local development.
 */

export const BACKEND_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL !== undefined
    ? process.env.NEXT_PUBLIC_API_URL
    : typeof window !== "undefined"
      ? ""
      : "http://127.0.0.1:8000";


const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function backendUrl(pathOrUrl: string): string {
  if (typeof window !== "undefined") {
    // In browser, always use relative paths so Next.js rewrites proxy to backend via IPv4
    if (BACKEND_BASE_URL && pathOrUrl.startsWith(BACKEND_BASE_URL)) {
      pathOrUrl = pathOrUrl.slice(BACKEND_BASE_URL.length);
    } else if (pathOrUrl.startsWith("http://localhost:8000") || pathOrUrl.startsWith("http://127.0.0.1:8000")) {
      try {
        const u = new URL(pathOrUrl);
        pathOrUrl = u.pathname + u.search;
      } catch {
        // ignore
      }
    }
    if (pathOrUrl.startsWith("http")) return pathOrUrl;
    return pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  }
  if (pathOrUrl.startsWith("http")) return pathOrUrl;
  return `${BACKEND_BASE_URL || "http://127.0.0.1:8000"}${pathOrUrl}`;
}

type ApiHealthListener = (healthy: boolean) => void;

const healthListeners = new Set<ApiHealthListener>();
let apiHealthy = true;

function setApiHealthy(next: boolean) {
  if (next === apiHealthy) return;
  apiHealthy = next;
  healthListeners.forEach((listener) => listener(next));
}

/** Subscribe to API reachability (fed by every `apiFetch`). Calls back immediately with the current state. */
export function onApiHealthChange(listener: ApiHealthListener): () => void {
  healthListeners.add(listener);
  listener(apiHealthy);
  return () => {
    healthListeners.delete(listener);
  };
}

export function apiFetch(pathOrUrl: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!SAFE_METHODS.has(method)) headers.set("X-EstateOS-Client", "dashboard");
  return fetch(backendUrl(pathOrUrl), { ...init, headers, credentials: "include" }).then(
    (response) => {
      setApiHealthy(response.status < 500);
      return response;
    },
    (error: unknown) => {
      // A component aborting its own request on unmount says nothing about the server.
      if (!(error instanceof DOMException && error.name === "AbortError")) setApiHealthy(false);
      throw error;
    }
  );
}
