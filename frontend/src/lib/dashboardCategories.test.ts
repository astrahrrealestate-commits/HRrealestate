import { describe, expect, it } from "vitest";
import {
  buildAllBucket,
  buildCategoryBrief,
  buildCategoryBuckets,
  DASHBOARD_CATEGORIES,
  mapThreadCategory,
  pickDefaultCategory,
} from "./dashboardCategories";
import type { InboxThread } from "@/types/inbox";
import type { AttentionItem } from "@/lib/api";

function makeThread(overrides: Partial<InboxThread> = {}): InboxThread {
  return {
    id: "t-1",
    caseRef: "#cs-001",
    channel: "gmail",
    recipientRole: "tenant",
    recipientRoleDetail: "Tenant",
    externalMessageId: "ext-1",
    senderName: "Pieter Bakker",
    senderContact: "p@example.nl",
    unitLabel: "Pieter Floriszstraat 1 C",
    buildingName: "Centrum",
    category: "maintenance",
    urgency: "normal",
    status: "needs_approval",
    receivedAt: "2026-11-26T08:00:00Z",
    relativeTime: "Today",
    latestSnippet: "Tap is leaking",
    messages: [],
    ...overrides,
  };
}

describe("mapThreadCategory", () => {
  it("maps legacy 8 categories and M13 6 categories accurately while hiding spam", () => {
    expect(mapThreadCategory({ category: "maintenance", recipientRole: "tenant", recipientRoleDetail: "Tenant" })).toBe("maintenance");
    expect(mapThreadCategory({ category: "complaint", recipientRole: "tenant", recipientRoleDetail: "Tenant" })).toBe("maintenance");
    expect(mapThreadCategory({ category: "contractor_update", recipientRole: "contractor", recipientRoleDetail: "Contractor" })).toBe("maintenance");
    expect(mapThreadCategory({ category: "payment", recipientRole: "tenant", recipientRoleDetail: "Tenant" })).toBe("finance");
    expect(mapThreadCategory({ category: "contractor_invoices", recipientRole: "contractor", recipientRoleDetail: "Contractor" })).toBe("finance");
    expect(mapThreadCategory({ category: "lease", recipientRole: "tenant", recipientRoleDetail: "Tenant" })).toBe("legal");
    expect(mapThreadCategory({ category: "admin", senderKind: "business", recipientRole: "contact", recipientRoleDetail: "Business" })).toBe("business");
    expect(mapThreadCategory({ category: "admin", recipientRole: "contact", recipientRoleDetail: "Contact" })).toBe("administration");
    expect(mapThreadCategory({ category: "new_projects", recipientRole: "contact", recipientRoleDetail: "Contact" })).toBe("new_projects");
    expect(mapThreadCategory({ category: "spam", recipientRole: "contact", recipientRoleDetail: "Contact" })).toBeNull();
  });
});

describe("buildCategoryBuckets & pickDefaultCategory", () => {
  it("groups items into Urgent and Open sorted by urgencyRank then draft readiness", () => {
    const threads = [
      makeThread({ id: "t-norm", category: "maintenance", urgency: "normal", receivedAt: "2026-11-26T09:00:00Z" }),
      makeThread({ id: "t-emerg", category: "maintenance", urgency: "emergency", receivedAt: "2026-11-26T07:00:00Z" }),
      makeThread({
        id: "t-high-draft",
        category: "maintenance",
        urgency: "high",
        receivedAt: "2026-11-26T06:00:00Z",
        draftProposal: {
          confidence: 0.9,
          recommendedAction: "Send",
          activeChannel: "gmail",
          whatsappDrafts: [],
          gmailDrafts: [],
          drafts: [
            {
              id: "d1",
              version: 1,
              label: "Draft",
              text: "We sturen een monteur.",
              tone: "direct",
              channel: "gmail",
              recipientType: "tenant",
              recipientName: "Pieter",
            },
          ],
        },
      }),
      makeThread({ id: "t-spam", category: "spam" as InboxThread["category"], urgency: "emergency" }),
      makeThread({ id: "t-fin-urgent", category: "payment", urgency: "high" }),
      makeThread({ id: "t-fin-urgent-2", category: "payment", urgency: "emergency" }),
    ];

    const attentionItems: AttentionItem[] = [
      {
        id: "lease-1",
        kind: "lease",
        title: "Lease ends 30-11-2026",
        detail: "Ends in 4 days",
        unitLabel: "Pieter Honszstraat 1 D",
        partyName: "M. Wincalowicz",
        urgent: true,
        ageDays: 4,
        href: "/properties",
        source: "brixx",
      },
      {
        id: "rent-1",
        kind: "rent",
        title: "€1.200 rent overdue",
        detail: "2 months unpaid",
        unitLabel: "Singel 1",
        partyName: "Tenant A",
        urgent: true,
        ageDays: 75,
        href: "/money",
        source: "brixx",
      },
    ];

    const buckets = buildCategoryBuckets({ threads, attentionItems });

    expect(DASHBOARD_CATEGORIES).toHaveLength(6);
    // Spam is excluded everywhere
    const allIds = Object.values(buckets).flatMap((b) => b.allItems.map((i) => i.id));
    expect(allIds).not.toContain("thread:t-spam");

    // Maintenance has 2 urgent (emergency before high) and 1 open
    expect(buckets.maintenance.urgentItems.map((i) => i.id)).toEqual(["thread:t-emerg", "thread:t-high-draft"]);
    expect(buckets.maintenance.openItems.map((i) => i.id)).toEqual(["thread:t-norm"]);

    // Finance has 2 urgent threads + 1 non-urgent rent attention (unreconciled rent excluded from urgent)
    expect(buckets.finance.urgentCount).toBe(2);
    expect(buckets.finance.openItems.map((i) => i.id)).toEqual(["att:rent-1"]);

    // Legal got the urgent lease from BRIXX
    expect(buckets.legal.urgentItems.map((i) => i.id)).toEqual(["att:lease-1"]);

    // Finance and Maintenance tie at 2 urgent, Maintenance has 3 open vs Finance 3 open -> Maintenance first in order
    expect(pickDefaultCategory(buckets)).toBe("maintenance");

    const allWithoutBrixx = buildAllBucket(buckets, { includeBrixx: false });
    expect(allWithoutBrixx.urgentCount).toBe(4);
    expect(allWithoutBrixx.openCount).toBe(5);
  });

  it("builds concise count-based briefs", () => {
    const buckets = buildCategoryBuckets({
      threads: [makeThread({ id: "t-1", category: "lease", urgency: "high" })],
      attentionItems: [],
    });
    expect(buildCategoryBrief(buckets.legal)).toBe("Legal — 1 urgent.");
    expect(buildCategoryBrief(buckets.new_projects)).toBe(
      "All clear in New Projects — nothing currently needs your attention."
    );
  });
});
