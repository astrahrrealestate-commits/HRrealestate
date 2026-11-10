/** Global search for the ⌘K palette (`GET /api/v1/search`). Titles are tenant-derived text: render as plain text. */

import { ensureAuthenticated } from "@/lib/api";
import { BACKEND_BASE_URL, apiFetch } from "@/lib/backend";

export interface SearchHit {
  kind: "person" | "unit" | "case" | "document";
  id: string;
  title: string;
  subtitle: string | null;
  person_kind: "tenant" | "contractor" | "owner" | "other" | null;
}

/** The hits, or null when the search itself failed (so the palette can say so instead of "nothing found"). */
export async function searchEverything(query: string, signal?: AbortSignal): Promise<SearchHit[] | null> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/search?${new URLSearchParams({ q: query })}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal,
    });
    if (res.ok) {
      const body = (await res.json()) as { hits: SearchHit[] };
      return body.hits;
    }
  } catch (err) {
    if (!(err instanceof DOMException && err.name === "AbortError")) console.warn("Search failed:", err);
  }
  return null;
}
