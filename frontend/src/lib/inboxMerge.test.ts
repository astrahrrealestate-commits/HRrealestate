import { describe, expect, it } from "vitest";
import { mergeFirstPage } from "@/lib/inboxMerge";

type Row = { id: string; isRead?: boolean; draft?: string };
const row = (id: string, extra: Partial<Row> = {}): Row => ({ id, ...extra });
const linked = (id: string) => (t: Row) => t.id === id;
const ids = (rows: Row[]) => rows.map((r) => r.id);
const base = { matches: linked("none"), fetchedThisVisit: new Set<string>(), firstOfVisit: false };

describe("mergeFirstPage", () => {
  it("drops last visit's deep-linked row on the first fetch, so it is fetched again before anyone approves it", () => {
    const prev = [row("old", { draft: "stale" }), row("a")];
    const out = mergeFirstPage(prev, [row("a")], { ...base, firstOfVisit: true, matches: linked("old") });
    expect(ids(out)).toEqual(["a"]);
  });

  it("keeps a row fetched by id during this visit", () => {
    const prev = [row("old"), row("a")];
    const options = { firstOfVisit: true, matches: linked("old"), fetchedThisVisit: new Set(["old"]) };
    expect(ids(mergeFirstPage(prev, [row("a")], options))).toEqual(["old", "a"]);
  });

  it("drops older pages kept from last visit, but not ones loaded during this visit", () => {
    const prev = Array.from({ length: 25 }, (_, i) => row(`t${i}`));
    const live = [row("t0")];
    expect(mergeFirstPage(prev, live, { ...base, firstOfVisit: true })).toEqual(live);
    expect(mergeFirstPage(prev, live, base)).toHaveLength(25);
  });

  it("keeps the read mark when the server does not say", () => {
    const out = mergeFirstPage([row("a", { isRead: true })], [row("a")], base);
    expect(out[0].isRead).toBe(true);
  });
});
