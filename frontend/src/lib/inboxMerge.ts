/** How a freshly fetched first page joins the rows the inbox already holds. */
interface Row {
  id: string;
  isRead?: boolean;
}

export interface MergeOptions<T> {
  /** The first answer since this page was opened: rows held until now are last visit's. */
  firstOfVisit: boolean;
  /** Whether a row is the one the URL points at (kept even when it is older than the first page). */
  matches: (row: T) => boolean;
  /** Rows fetched one by one during this visit, current although outside the first page. */
  fetchedThisVisit: ReadonlySet<string>;
}

const PAGE = 20;

export function mergeFirstPage<T extends Row>(prev: T[], live: T[], options: MergeOptions<T>): T[] {
  const { firstOfVisit, matches, fetchedThisVisit } = options;
  const held = new Map(prev.map((t) => [t.id, t]));
  const merged = live.map((t) => {
    const old = held.get(t.id);
    return old ? { ...t, isRead: t.isRead !== undefined ? t.isRead : old.isRead } : t;
  });
  const liveIds = new Set(merged.map((t) => t.id));
  const outside = prev.filter((t) => !liveIds.has(t.id));
  if (!firstOfVisit && prev.length > PAGE) return merged.concat(outside);
  const pinned = outside.filter((t) => matches(t) && (!firstOfVisit || fetchedThisVisit.has(t.id)));
  return pinned.concat(merged);
}
