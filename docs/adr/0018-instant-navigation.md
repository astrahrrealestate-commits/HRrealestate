# ADR 0018: Instant navigation — kept shell, in-memory view cache, compressed responses

Status: accepted (2026-11-27)

## Context

Moving between dashboard pages felt like a full reload and data already in Postgres appeared slowly. Measured on a
copy of local data (14 cases, 1,181 messages), read endpoints answered in 4–43 ms warm with flat query counts, so
neither the queries nor the connection pool (15 + 20) were the cause. The causes were in delivery:

- every page mounted its own `Sidebar` and started with empty state, so each visit showed a spinner and refetched;
- responses were uncompressed: the inbox list was 183 KB (26 KB gzipped) and an open inbox re-reads it every 8 s.

## Decision

1. `AppFrame` in the root layout mounts the sidebar once; pages render only their own content.
2. `lib/viewCache.ts` (a module `Map`) and `useCachedState` keep what a page last showed. A page paints that at once
   and still fetches and polls as before. The setter writes the cache itself, so a rollback or late answer after the
   page has gone is recorded. A value is cached with the query that produced it (month, briefing kind, audience).
   Error states and permission data (team admin) are not cached. Memory only, never browser storage.
   The cache is dropped on logout and when the signed-in profile or its access changes: any 401 or 403 from a data
   endpoint, and a tab coming back into view, re-read `/api/auth/me`; a changed answer reloads the page.
3. Starlette's `GZipMiddleware` compresses responses over 1,000 bytes. It leaves `text/event-stream` alone, so the
   Super Agent still streams.

## Why not SWR or TanStack Query

Pages load with imperative fetches and apply optimistic updates to local state. A data-fetching library would mean
rewriting that logic page by page. Swapping `useState` for `useCachedState` gets instant revisits without touching
it. If request deduplication or invalidation is needed later, move to SWR then.

## Consequences

- A page shows data from the last visit until its fetch answers, longer if that fetch fails. So nothing is decided
  on a cached copy: send, approve and reject (inbox), save and dispatch (maintenance), calendar approve and invite
  RSVP wait for this visit's fetch, a chat is marked read only after it, and inbox rows past the first page are
  dropped on that fetch.
- Sends are still decided server side (approval status, `draft_version`, recipient from the database). A draft that
  changes under an open composer is still replaced without notice, as it was between polls before this change.
- Loaders that answer with an empty list on failure still overwrite the cached list with it.
- The first visit to a page is no faster apart from compression. Calendar and invite cards still call Google in the
  request path.
- The sidebar badge shows the open page's own count when it has one, else `GET /api/inbox/stats`.
- A new page must not render `Sidebar` itself. New cached data needs a key that includes its query.
