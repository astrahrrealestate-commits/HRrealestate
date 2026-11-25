import { InboxThread } from "@/types/inbox";
import { isNeedsYou } from "@/lib/selectors";
import { SHOWN_CATEGORIES } from "@/lib/categoryLabels";

/** What each option of the inbox filter popover keeps. Ids are `<group>_<name>`; a group is the part before `_`. */
const OPTION_PREDICATES: Record<string, (t: InboxThread) => boolean> = {
  who_tenants: (t) => t.senderKind === "tenant" || t.recipientRole === "tenant",
  who_contractors: (t) => t.senderKind === "contractor" || t.recipientRole === "contractor",
  who_legal: (t) => t.senderKind === "legal" || t.recipientRoleDetail?.toLowerCase() === "legal",
  who_vve: (t) => t.senderKind === "vve" || t.recipientRoleDetail?.toLowerCase() === "vve",
  who_business: (t) =>
    t.senderKind === "business" ||
    ["business", "utility", "municipality"].includes((t.recipientRoleDetail || "").toLowerCase()),
  who_leads: (t) => t.senderKind === "prospect" || t.recipientRole === "inquiry",
  who_others: (t) => (!t.senderKind || t.senderKind === "contact") && t.recipientRole === "contact",
  ch_whatsapp: (t) => t.channel === "whatsapp",
  ch_gmail: (t) => t.channel === "gmail",
  ch_portal: (t) => t.channel === "portal",
  ...Object.fromEntries(
    SHOWN_CATEGORIES.map((c) => [`type_${c}`, (t: InboxThread) => t.category === c] as const)
  ),
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
