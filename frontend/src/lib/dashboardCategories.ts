import { InboxThread } from "@/types/inbox";
import { AttentionItem, CalendarEvent, MaintenanceTicket, ProspectiveInquiry } from "@/lib/api";
import { StalledItem } from "@/components/today/UnresponsiveRadarCard";
import { isNeedsYou, isUrgent } from "@/lib/selectors";
import { formatListTime } from "@/lib/dateUtils";

export type DashboardCategoryId =
  | "maintenance"
  | "finance"
  | "legal"
  | "business"
  | "administration"
  | "new_projects";

export type DashboardTabId = "all" | DashboardCategoryId;

export interface DashboardCategoryMeta {
  id: DashboardCategoryId;
  label: string;
  description: string;
}

export const DASHBOARD_CATEGORIES: DashboardCategoryMeta[] = [
  { id: "maintenance", label: "Maintenance", description: "Repairs, tickets & contractors" },
  { id: "finance", label: "Finance", description: "Rent, invoices & quotes" },
  { id: "legal", label: "Legal", description: "Leases, renewals & disputes" },
  { id: "business", label: "Business", description: "Partners, leads & vendors" },
  { id: "administration", label: "Administration", description: "Municipal, VvE & admin" },
  { id: "new_projects", label: "New Projects", description: "Developments & acquisitions" },
];

export type DashboardItemKind = "thread" | "brixx_ticket" | "brixx_rent" | "brixx_lease" | "calendar" | "radar" | "lead";

export interface DashboardItem {
  id: string;
  kind: DashboardItemKind;
  category: DashboardCategoryId;
  group: "urgent" | "open";
  urgencyRank: number; // 0 = emergency/urgent, 1 = high, 2 = normal, 3 = low
  title: string;
  subtitle: string;
  unitLabel: string;
  partyName: string;
  channel?: string;
  timeLabel: string;
  hasDraft: boolean;
  isUnread: boolean;
  sortTimestamp: number;
  secondaryTag?: string;
  href?: string;
  thread?: InboxThread;
  attention?: AttentionItem;
  ticket?: MaintenanceTicket;
  calendarEvent?: CalendarEvent;
  radarItem?: StalledItem;
  inquiry?: ProspectiveInquiry;
}

export interface CategoryBucket {
  meta: DashboardCategoryMeta;
  urgentItems: DashboardItem[];
  openItems: DashboardItem[];
  allItems: DashboardItem[];
  urgentCount: number;
  openCount: number;
  draftCount: number;
}

const URGENCY_RANK: Record<string, number> = {
  emergency: 0,
  high: 1,
  normal: 2,
  low: 3,
};

function isActivelySnoozed(thread: InboxThread): boolean {
  if (!thread.snoozedUntil) return false;
  const ts = new Date(thread.snoozedUntil).getTime();
  return !Number.isNaN(ts) && ts > Date.now();
}

export function isInternalSpam(category?: string): boolean {
  return (category || "").toLowerCase() === "spam";
}

/**
 * Maps both M13 6-category values and legacy 8-category values into the 6 main dashboard categories.
 * Returns null for internal spam so spam is never displayed on Today.
 */
export function mapThreadCategory(thread: {
  category?: string;
  senderKind?: string;
  recipientRole?: string;
  recipientRoleDetail?: string;
}): DashboardCategoryId | null {
  const cat = (thread.category || "").toLowerCase();
  if (cat === "spam") return null;

  if (cat === "maintenance" || cat === "complaint" || cat === "contractor_update" || cat === "contractor_repairs") {
    return "maintenance";
  }
  if (cat === "finance" || cat === "payment" || cat === "rent" || cat === "contractor_invoices") {
    return "finance";
  }
  if (cat === "legal" || cat === "lease" || cat === "sublet") {
    return "legal";
  }
  if (cat === "business") {
    return "business";
  }
  if (cat === "new_projects") {
    return "new_projects";
  }
  if (cat === "administration" || cat === "admin") {
    return inferFromSender(thread) ?? "administration";
  }

  // Fallback for "general" / "other"
  return inferFromSender(thread) ?? "administration";
}

function inferFromSender(thread: {
  senderKind?: string;
  recipientRole?: string;
  recipientRoleDetail?: string;
}): DashboardCategoryId | null {
  const kind = (thread.senderKind || "").toLowerCase();
  const detail = (thread.recipientRoleDetail || "").toLowerCase();
  if (kind === "legal" || detail === "legal") return "legal";
  if (kind === "contractor" || thread.recipientRole === "contractor") return "maintenance";
  if (kind === "business" || kind === "prospect" || thread.recipientRole === "inquiry") return "business";
  if (kind === "vve" || detail === "vve") return "administration";
  return null;
}

export function mapAttentionCategory(item: AttentionItem): DashboardCategoryId {
  if (item.kind === "ticket") return "maintenance";
  if (item.kind === "rent") return "finance";
  return "legal";
}

export function mapRadarCategory(item: StalledItem): DashboardCategoryId {
  if (item.type === "contractor_stalled") return "maintenance";
  if (item.type === "unpaid_rent") return "finance";
  return "legal";
}

export function mapCalendarCategory(evt: CalendarEvent): DashboardCategoryId {
  if (evt.eventType === "contractor_repair") return "maintenance";
  if (evt.eventType === "viewing") return "business";
  if (evt.eventType === "inspection") return "legal";
  return "administration";
}

function hasThreadDraft(thread: InboxThread): boolean {
  return Boolean(
    thread.draftProposal?.drafts?.length ||
      thread.draftProposal?.whatsappDrafts?.length ||
      thread.draftProposal?.gmailDrafts?.length
  );
}

function parseTimestamp(iso?: string): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}

function formatDueAge(item: AttentionItem): string {
  if (item.kind === "lease") return `${item.ageDays}d left`;
  if (item.kind === "rent") return `${item.ageDays}d late`;
  return `${item.ageDays}d open`;
}

export interface BuildBucketsInput {
  threads: InboxThread[];
  attentionItems: AttentionItem[];
  maintenanceTickets?: MaintenanceTicket[];
  radarItems?: StalledItem[];
  inquiries?: ProspectiveInquiry[];
  calendarEvents?: CalendarEvent[];
}

export function buildCategoryBuckets({
  threads,
  attentionItems,
  maintenanceTickets = [],
  radarItems = [],
  inquiries = [],
  calendarEvents = [],
}: BuildBucketsInput): Record<DashboardCategoryId, CategoryBucket> {
  const buckets = {} as Record<DashboardCategoryId, CategoryBucket>;
  for (const meta of DASHBOARD_CATEGORIES) {
    buckets[meta.id] = {
      meta,
      urgentItems: [],
      openItems: [],
      allItems: [],
      urgentCount: 0,
      openCount: 0,
      draftCount: 0,
    };
  }

  const pushItem = (item: DashboardItem) => {
    const bucket = buckets[item.category];
    if (item.group === "urgent") {
      bucket.urgentItems.push(item);
    } else {
      bucket.openItems.push(item);
    }
  };

  // 1. Live Inbox Threads needing action or marked urgent (excluding spam, closed/rejected, snoozed)
  for (const thread of threads) {
    if (isInternalSpam(thread.category)) continue;
    if (thread.status === "closed" || thread.status === "rejected" || thread.status === "approved" || thread.status === "replied") {
      continue;
    }
    if (isActivelySnoozed(thread)) continue;

    const threadUrgent = isUrgent(thread);
    const needsAction = isNeedsYou(thread);
    if (!needsAction && !threadUrgent) continue;

    const category = mapThreadCategory(thread);
    if (!category) continue;

    const draftReady = hasThreadDraft(thread);
    const rank = URGENCY_RANK[thread.urgency] ?? (threadUrgent ? 1 : 2);
    const timeStr = formatListTime(thread.receivedAt) || thread.relativeTime || "";

    pushItem({
      id: `thread:${thread.id}`,
      kind: "thread",
      category,
      group: threadUrgent ? "urgent" : "open",
      urgencyRank: rank,
      title: thread.subject || thread.issueTitle || thread.latestSnippet || "Message",
      subtitle: thread.latestSnippet || "",
      unitLabel: thread.unitLabel || "",
      partyName: thread.senderName || "Unknown",
      channel: thread.channel,
      timeLabel: timeStr,
      hasDraft: draftReady,
      isUnread: thread.isRead === false || (thread.isRead === undefined && needsAction),
      sortTimestamp: parseTimestamp(thread.receivedAt),
      thread,
    });
  }

  // 2. BRIXX Attention items (tickets, rent arrears, ending leases)
  for (const att of attentionItems) {
    const category = mapAttentionCategory(att);
    const isRent = att.kind === "rent";
    // Mirror existing domain rule: unreconciled rent stays out of urgent emergencies until settled in Exact Online
    const itemUrgent = Boolean(att.urgent) && !isRent;
    const matchedTicket =
      att.kind === "ticket"
        ? maintenanceTickets.find((t) => t.id === att.id || t.ticketNumber === att.id)
        : undefined;

    pushItem({
      id: `att:${att.id}`,
      kind: att.kind === "ticket" ? "brixx_ticket" : isRent ? "brixx_rent" : "brixx_lease",
      category,
      group: itemUrgent ? "urgent" : "open",
      urgencyRank: itemUrgent ? 1 : 2,
      title: isRent ? att.title.replace("rent overdue", "rent billed") : att.title,
      subtitle: att.detail,
      unitLabel: att.unitLabel,
      partyName: att.partyName || "BRIXX",
      channel: "brixx",
      timeLabel: formatDueAge(att),
      hasDraft: false,
      isUnread: itemUrgent,
      sortTimestamp: att.kind === "lease" ? -att.ageDays : att.ageDays,
      secondaryTag: "BRIXX",
      href: att.href,
      attention: att,
      ticket: matchedTicket,
    });
  }

  // 3. Stalled / Unresponsive waits from Radar
  for (const radar of radarItems) {
    const category = mapRadarCategory(radar);
    pushItem({
      id: `radar:${radar.id}`,
      kind: "radar",
      category,
      group: radar.daysStalled >= 7 ? "urgent" : "open",
      urgencyRank: radar.daysStalled >= 7 ? 1 : 2,
      title: radar.subject,
      subtitle: `${radar.daysStalled}d waiting · ${radar.remindersSentCount} reminder${radar.remindersSentCount === 1 ? "" : "s"} sent`,
      unitLabel: radar.unitLabel,
      partyName: radar.partyName,
      channel: "radar",
      timeLabel: `${radar.daysStalled}d waiting`,
      hasDraft: Boolean(radar.proposedActionDraft),
      isUnread: false,
      sortTimestamp: radar.daysStalled,
      secondaryTag: "Waiting",
      radarItem: radar,
    });
  }

  // 4. Prospective Inquiries -> Business
  for (const lead of inquiries) {
    pushItem({
      id: `lead:${lead.id}`,
      kind: "lead",
      category: "business",
      group: "open",
      urgencyRank: 2,
      title: lead.request || "Prospective inquiry",
      subtitle: lead.qualification || lead.moveIn || "",
      unitLabel: lead.unit || "",
      partyName: lead.name,
      channel: lead.channel,
      timeLabel: lead.moveIn || "New",
      hasDraft: false,
      isUnread: true,
      sortTimestamp: 0,
      secondaryTag: "Lead",
      href: "/inbox?audience=inquiries",
      inquiry: lead,
    });
  }

  // 5. Pending Calendar Visits
  for (const evt of calendarEvents) {
    if (evt.status !== "proposed") continue;
    const category = mapCalendarCategory(evt);
    const startTs = parseTimestamp(evt.startTime);
    pushItem({
      id: `cal:${evt.id}`,
      kind: "calendar",
      category,
      group: "open",
      urgencyRank: 2,
      title: evt.title,
      subtitle: evt.description || evt.attendees?.[0]?.displayName || "Proposed visit awaiting approval",
      unitLabel: evt.location || "",
      partyName: evt.attendees?.[0]?.displayName || "Visit",
      channel: "calendar",
      timeLabel: formatListTime(evt.startTime) || "Visit",
      hasDraft: false,
      isUnread: true,
      sortTimestamp: startTs,
      secondaryTag: "Visit",
      calendarEvent: evt,
    });
  }

  const compareItems = (a: DashboardItem, b: DashboardItem): number => {
    if (a.urgencyRank !== b.urgencyRank) return a.urgencyRank - b.urgencyRank;
    if (a.hasDraft !== b.hasDraft) return a.hasDraft ? -1 : 1;
    if (a.kind === "thread" && b.kind !== "thread") return -1;
    if (a.kind !== "thread" && b.kind === "thread") return 1;
    return b.sortTimestamp - a.sortTimestamp;
  };

  for (const meta of DASHBOARD_CATEGORIES) {
    const bucket = buckets[meta.id];
    bucket.urgentItems.sort(compareItems);
    bucket.openItems.sort(compareItems);
    bucket.allItems = [...bucket.urgentItems, ...bucket.openItems];
    bucket.urgentCount = bucket.urgentItems.length;
    bucket.openCount = bucket.allItems.length;
    bucket.draftCount = bucket.allItems.filter((i) => i.hasDraft).length;
  }

  return buckets;
}

/**
 * Combines items across all 6 categories for the "All" tab, sorted URGENT -> OPEN.
 * Optionally excludes BRIXX / Calendar items when dedicated cards render them below.
 */
export function buildAllBucket(
  buckets: Record<DashboardCategoryId, CategoryBucket>,
  options: { includeBrixx?: boolean; includeCalendar?: boolean } = {}
): CategoryBucket {
  const { includeBrixx = false, includeCalendar = false } = options;
  const keep = (item: DashboardItem) => {
    if (!includeBrixx && (item.kind === "brixx_ticket" || item.kind === "brixx_rent" || item.kind === "brixx_lease")) {
      return false;
    }
    if (!includeCalendar && item.kind === "calendar") {
      return false;
    }
    return true;
  };

  const urgentItems = DASHBOARD_CATEGORIES.flatMap((m) => buckets[m.id].urgentItems.filter(keep));
  const openItems = DASHBOARD_CATEGORIES.flatMap((m) => buckets[m.id].openItems.filter(keep));
  const compareItems = (a: DashboardItem, b: DashboardItem): number => {
    if (a.urgencyRank !== b.urgencyRank) return a.urgencyRank - b.urgencyRank;
    if (a.hasDraft !== b.hasDraft) return a.hasDraft ? -1 : 1;
    if (a.kind === "thread" && b.kind !== "thread") return -1;
    if (a.kind !== "thread" && b.kind === "thread") return 1;
    return b.sortTimestamp - a.sortTimestamp;
  };
  urgentItems.sort(compareItems);
  openItems.sort(compareItems);
  const allItems = [...urgentItems, ...openItems];

  return {
    meta: { id: "maintenance", label: "All", description: "Everything across all categories" },
    urgentItems,
    openItems,
    allItems,
    urgentCount: urgentItems.length,
    openCount: allItems.length,
    draftCount: allItems.filter((i) => i.hasDraft).length,
  };
}

/**
 * Selects the category with the most urgent items on initial load; falls back to most open items, then Maintenance.
 */
export function pickDefaultCategory(buckets: Record<DashboardCategoryId, CategoryBucket>): DashboardCategoryId {
  let bestId: DashboardCategoryId = "maintenance";
  let bestUrgent = -1;
  let bestOpen = -1;

  for (const meta of DASHBOARD_CATEGORIES) {
    const b = buckets[meta.id];
    if (b.urgentCount > bestUrgent || (b.urgentCount === bestUrgent && b.openCount > bestOpen)) {
      bestId = meta.id;
      bestUrgent = b.urgentCount;
      bestOpen = b.openCount;
    }
  }
  return bestId;
}

/**
 * Deterministic 1-line category brief built solely from real counts (no model invention).
 */
export function buildCategoryBrief(bucket: CategoryBucket): string {
  const { meta, urgentCount, openCount, draftCount } = bucket;
  if (openCount === 0) {
    return `All clear in ${meta.label} — nothing currently needs your attention.`;
  }
  const parts: string[] = [];
  if (urgentCount > 0) parts.push(`${urgentCount} urgent`);
  if (draftCount > 0) parts.push(`${draftCount} AI draft${draftCount === 1 ? "" : "s"} ready`);
  const remaining = Math.max(0, openCount - urgentCount);
  if (remaining > 0) parts.push(`${remaining} open`);
  return `${meta.label} — ${parts.join(" · ")}.`;
}
