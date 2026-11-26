import { describe, expect, it } from "vitest";
import { sourceChips } from "./sources";

describe("sourceChips", () => {
  it("shows every source by its label and kind", () => {
    const chips = sourceChips([
      { kind: "message", ref: "0001", label: "Anna, gmail, 2026-09-01" },
      { kind: "document", ref: "0002", label: "Huurovereenkomst (lease)" },
      { kind: "data", ref: "query 1", label: "Checked the database (2 rows)" },
    ]);
    expect(chips.map((c) => [c.kind, c.label])).toEqual([
      ["message", "Anna, gmail, 2026-09-01"],
      ["document", "Huurovereenkomst (lease)"],
      ["data", "Checked the database (2 rows)"],
    ]);
    expect(chips.every((c) => c.href === null)).toBe(true);
  });

  it("opens a web page only over https", () => {
    const chips = sourceChips([
      { kind: "web", ref: "https://wetten.overheid.nl/BWBR0005290", label: "Burgerlijk Wetboek 7" },
      { kind: "web", ref: "javascript:alert(1)", label: "evil" },
      { kind: "web", ref: "http://example.test", label: "plain http" },
    ]);
    expect(chips.map((c) => c.href)).toEqual(["https://wetten.overheid.nl/BWBR0005290", null, null]);
  });

  it("drops duplicates and blank labels, and copes with a missing list", () => {
    const one = { kind: "message" as const, ref: "1", label: "Anna" };
    expect(sourceChips([one, one, { kind: "data", ref: "2", label: "  " }])).toHaveLength(1);
    expect(sourceChips(undefined)).toEqual([]);
  });
});


describe("sourceChips keys", () => {
  it("gives two mails with the same label different keys", () => {
    const chips = sourceChips([
      { kind: "message", ref: "1", label: "Anna, gmail, 2026-09-01" },
      { kind: "message", ref: "2", label: "Anna, gmail, 2026-09-01" },
    ]);
    expect(new Set(chips.map((c) => c.key)).size).toBe(2);
  });
});
