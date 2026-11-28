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

  it("filters by urgency and month/year period cleanly", () => {
    const novEmergency = {
      category: "maintenance",
      channel: "gmail",
      urgency: "emergency",
      receivedAt: "2026-11-28T10:00:00Z",
    } as unknown as InboxThread;
    const octNormal = {
      category: "finance",
      channel: "gmail",
      urgency: "normal",
      receivedAt: "2026-10-14T10:00:00Z",
    } as unknown as InboxThread;

    expect(matchesFilters(novEmergency, ["urg_emergency"])).toBe(true);
    expect(matchesFilters(octNormal, ["urg_emergency"])).toBe(false);
    expect(matchesFilters(octNormal, ["urg_low"])).toBe(true);
    expect(matchesFilters(novEmergency, ["urg_low"])).toBe(false);
    expect(matchesFilters(octNormal, ["period_2026-10"])).toBe(true);
    expect(matchesFilters(novEmergency, ["period_2026-10"])).toBe(false);
    expect(matchesFilters(octNormal, ["period_2026"])).toBe(true);
    expect(matchesFilters(octNormal, ["period_2025"])).toBe(false);
  });
});
