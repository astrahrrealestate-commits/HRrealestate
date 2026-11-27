/**
 * What each page last showed, kept in memory so going back to a page paints at once while it refetches (ADR 0018).
 * Memory only: nothing is written to browser storage, and a reload starts empty. AuthContext drops it on logout and
 * when the signed-in profile or its access changes.
 */
const views = new Map<string, unknown>();

export function readView<T>(key: string): T | undefined {
  return views.get(key) as T | undefined;
}

export function writeView<T>(key: string, value: T): void {
  views.set(key, value);
}

/** Applies a `setState` action to the cached value (`fallback` before there is one) and records the result. */
export function updateView<T>(key: string, action: T | ((prev: T) => T), fallback: T): T {
  const prev = views.has(key) ? (views.get(key) as T) : fallback;
  const next = typeof action === "function" ? (action as (prev: T) => T)(prev) : action;
  views.set(key, next);
  return next;
}

/** Drops one view, for data a send has just made out of date. */
export function forgetView(key: string): void {
  views.delete(key);
}

export function clearViews(): void {
  views.clear();
}
