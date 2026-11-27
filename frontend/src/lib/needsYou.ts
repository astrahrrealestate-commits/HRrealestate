/**
 * The open page's own "needs you" count, for the sidebar that now lives outside it. A page that knows the count
 * (it excludes snoozed threads and follows his clicks at once) wins over the sidebar's polled total.
 */
let pageCount: number | null = null;
const listeners = new Set<() => void>();

export function setPageNeedsYou(count: number | null): void {
  if (count === pageCount) return;
  pageCount = count;
  listeners.forEach((listener) => listener());
}

export function getPageNeedsYou(): number | null {
  return pageCount;
}

export function subscribeNeedsYou(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
