import { InboxThread } from "@/types/inbox";
import { isNeedsYou } from "@/lib/selectors";

/** What each option of the inbox filter popover keeps. Ids are `<group>_<name>`; a group is the part before `_`. */
const OPTION_PREDICATES: Record<string, (t: InboxThread) => boolean> = {
  who_tenants: (t) => t.recipientRole === "tenant",
  who_contractors: (t) => t.recipientRole === "contractor",
  who_leads: (t) => t.recipientRole === "inquiry",
  who_others: (t) => t.recipientRole === "contact",
  ch_whatsapp: (t) => t.channel === "whatsapp",
  ch_gmail: (t) => t.channel === "gmail",
  ch_portal: (t) => t.channel === "portal",
  type_repairs: (t) => t.category === "maintenance" || t.category === "contractor_repairs",
  type_rent: (t) => t.category === "rent" || t.category === "payment",
  type_lease: (t) => t.category === "lease" || t.category === "sublet",
  type_complaint: (t) => t.category === "complaint",
  type_contractor: (t) =>
    t.category === "contractor_update" ||
    t.category === "contractor_repairs" ||
    t.category === "contractor_invoices",
  type_admin: (t) => t.category === "admin",
};

const groupOf = (optionId: string) => optionId.split("_")[0];

/** Within one group the selected options widen the result (or); across groups they narrow it (and). */
export function matchesFilters(thread: InboxThread, selectedIds: string[], exceptGroup?: string): boolean {
  const byGroup = new Map<string, string[]>();
  for (const id of selectedIds) {
    const group = groupOf(id);
    if (group === exceptGroup) continue;
    byGroup.set(group, [...(byGroup.get(group) ?? []), id]);
  }
  return [...byGroup.values()].every((ids) => ids.some((id) => OPTION_PREDICATES[id]?.(thread) ?? false));
}

export function isActivelySnoozed(thread: InboxThread): boolean {
  if (!thread.snoozedUntil) return false;
  const until = new Date(thread.snoozedUntil).getTime();
  return !Number.isNaN(until) && until > Date.now();
}

export function matchesTab(thread: InboxThread, tab: string): boolean {
  if (tab === "snoozed") return isActivelySnoozed(thread);
  if (tab === "unread") {
    return thread.isRead === false || (thread.isRead === undefined && isNeedsYou(thread));
  }
  if (tab === "needs_you") return isNeedsYou(thread) && !isActivelySnoozed(thread);
  if (tab === "done") return !isNeedsYou(thread) && !isActivelySnoozed(thread);
  return true;
}

/**
 * The badge on a filter option: how many threads the list would show with that option ticked, given the active tab
 * and the options already ticked in the other groups.
 */
export function optionCount(threads: InboxThread[], tab: string, selectedIds: string[], optionId: string): number {
  const predicate = OPTION_PREDICATES[optionId];
  if (!predicate) return 0;
  return threads.filter(
    (t) => matchesTab(t, tab) && matchesFilters(t, selectedIds, groupOf(optionId)) && predicate(t)
  ).length;
}
