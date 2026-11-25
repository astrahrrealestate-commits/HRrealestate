import { describe, expect, it } from "vitest";
import { matchesFilters } from "./inboxFilters";
import { SHOWN_CATEGORIES, categoryLabel } from "./categoryLabels";
import type { InboxThread } from "@/types/inbox";

const thread = (category: string) => ({ category, channel: "gmail" }) as unknown as InboxThread;

describe("inbox type filter", () => {
  it("lists the six business categories in display order", () => {
    expect(SHOWN_CATEGORIES).toEqual(["maintenance", "finance", "legal", "business", "administration", "new_projects"]);
    expect(SHOWN_CATEGORIES.map((c) => categoryLabel(c, "en"))).toEqual([
      "Maintenance",
      "Finance",
      "Legal",
      "Business",
      "Administration",
      "New projects",
    ]);
  });

  it.each(SHOWN_CATEGORIES)("filters by %s and nothing else", (category) => {
    for (const other of SHOWN_CATEGORIES) {
      expect(matchesFilters(thread(other), [`type_${category}`])).toBe(other === category);
    }
  });

  it("gives an old or unknown category no label", () => {
    expect(categoryLabel("contractor_update", "en")).toBeNull();
    expect(categoryLabel("spam", "en")).toBeNull();
  });
});
