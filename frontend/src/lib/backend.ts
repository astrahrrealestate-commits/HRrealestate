/**
 * The one way the SPA talks to the EstateOS API.
 *
 * `apiFetch` always sends the session cookie (`credentials: "include"`) and, for anything that changes state, the
 * `X-EstateOS-Client` header the API requires as its third CSRF layer. Never call `fetch` on the backend directly: a
 * bare `fetch` sends no cookie, so every dashboard route answers 401 outside local development.
 */

const isLocalhost =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1" ||
    window.location.hostname.endsWith(".localhost"));

export const BACKEND_BASE_URL =
  typeof window !== "undefined" && isLocalhost
    ? ""
    : process.env.NEXT_PUBLIC_API_URL !== undefined
      ? process.env.NEXT_PUBLIC_API_URL
      : typeof window !== "undefined"
        ? ""
        : "http://127.0.0.1:8000";


const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export function backendUrl(pathOrUrl: string): string {
  if (typeof window !== "undefined" && isLocalhost) {
    // In local browser development, always use relative paths so Next.js rewrites proxy to backend via IPv4
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
  const base = BACKEND_BASE_URL || (typeof window === "undefined" ? "http://127.0.0.1:8000" : "");
  if (!base) return pathOrUrl.startsWith("/") ? pathOrUrl : `/${pathOrUrl}`;
  return `${base.replace(/\/+$/, "")}/${pathOrUrl.replace(/^\/+/, "")}`;
}

type ApiHealthListener = (healthy: boolean) => void;

const healthListeners = new Set<ApiHealthListener>();
let apiHealthy = true;
let consecutiveFailures = 0;
let verifyTimer: ReturnType<typeof setTimeout> | null = null;
let probeInFlight: Promise<boolean> | null = null;
const FAILURE_THRESHOLD = 2;
const WAKE_VERIFY_DELAY_MS = 1500;
const GATEWAY_UNAVAILABLE_STATUSES = new Set([502, 503, 504]);

function setApiHealthy(next: boolean) {
  if (next) {
    consecutiveFailures = 0;
    if (verifyTimer !== null) {
      clearTimeout(verifyTimer);
      verifyTimer = null;
    }
  }
  if (next === apiHealthy) return;
  apiHealthy = next;
  healthListeners.forEach((listener) => listener(next));
}

function isAbortOrTimeout(error: unknown): "abort" | "timeout" | null {
  if (error instanceof DOMException) {
    if (error.name === "AbortError") return "abort";
    if (error.name === "TimeoutError") return "timeout";
  }
  return null;
}

function scheduleHealthVerification() {
  if (verifyTimer !== null || !apiHealthy) return;
  // Wait briefly so wake-up sockets and Wi-Fi reconnects settle before flipping the global banner.
  verifyTimer = setTimeout(() => {
    verifyTimer = null;
    void probeApiHealth();
  }, WAKE_VERIFY_DELAY_MS);
}

/** Check `/health/live` so wake-up and reconnect events restore reachability without waiting for a poll. */
export function probeApiHealth(): Promise<boolean> {
  if (probeInFlight) return probeInFlight;
  probeInFlight = fetch(backendUrl("/health/live"), {
    method: "GET",
    credentials: "include",
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  })
    .then(
      (res) => {
        if (res.ok) {
          setApiHealthy(true);
          return true;
        }
        if (GATEWAY_UNAVAILABLE_STATUSES.has(res.status)) {
          setApiHealthy(false);
          return false;
        }
        return apiHealthy;
      },
      () => {
        setApiHealthy(false);
        return false;
      }
    )
    .finally(() => {
      probeInFlight = null;
    });
  return probeInFlight;
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
      if (response.status < 500) {
        setApiHealthy(true);
      } else if (GATEWAY_UNAVAILABLE_STATUSES.has(response.status)) {
        consecutiveFailures += 1;
        if (consecutiveFailures >= FAILURE_THRESHOLD) scheduleHealthVerification();
      }
      return response;
    },
    (error: unknown) => {
      const kind = isAbortOrTimeout(error);
      if (kind === "abort") throw error;
      consecutiveFailures += 1;
      // Single timeouts reflect a slow query rather than an outage; confirm with `/health/live` after repeated hits.
      if (kind === "timeout") {
        if (consecutiveFailures >= FAILURE_THRESHOLD + 1) scheduleHealthVerification();
      } else if (consecutiveFailures >= FAILURE_THRESHOLD) {
        scheduleHealthVerification();
      }
      throw error;
    }
  );
}
