/** Pure helpers of the Chats page (no React, no I/O). */

import type { ChatItem, ChatMessage, DeliveryStatus, PersonKind } from "@/types/chats";

export type Tick = "pending" | "sent" | "delivered" | "read" | "failed";

const KIND_LABELS: Record<string, string> = {
  audio: "Voice message",
  image: "Photo",
  document: "Document",
};

/** The one-line preview of a chat row: the text, else the media kind; "You: " for our own last message. */
export function chatPreview(item: ChatItem): string {
  const text = item.last_text.trim();
  const body = text || KIND_LABELS[item.last_kind ?? ""] || "Message";
  return item.last_direction === "outbound" ? `You: ${body}` : body;
}

const dayKey = (tz: string) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" });
const dayLabel = (tz: string) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short", day: "numeric", month: "short" });

/** Messages grouped by calendar day in `tz`, order kept. The label reads "Mon 23 Nov". */
export function groupByDay(
  messages: ChatMessage[],
  tz: string
): Array<{ day: string; messages: ChatMessage[] }> {
  const key = dayKey(tz);
  const label = dayLabel(tz);
  const groups: Array<{ key: string; day: string; messages: ChatMessage[] }> = [];
  for (const m of messages) {
    const at = new Date(m.sent_at);
    const k = key.format(at);
    const last = groups[groups.length - 1];
    if (last && last.key === k) {
      last.messages.push(m);
    } else {
      groups.push({ key: k, day: label.format(at).replace(",", ""), messages: [m] });
    }
  }
  return groups.map(({ day, messages: ms }) => ({ day, messages: ms }));
}

/** The tick of an outbound message: no delivery status yet means it has not left (or was not confirmed) yet. */
export function tickFromStatus(status: DeliveryStatus | null, pending = false): Tick {
  if (status === "failed") return "failed";
  if (pending || status === null) return "pending";
  return status;
}

export function tickFor(m: ChatMessage): Tick {
  return tickFromStatus(m.delivery_status, m.pending);
}

export function totalUnread(items: ChatItem[]): number {
  return items.reduce((sum, c) => sum + c.unread, 0);
}

/** `before` cursor for the page older than what is loaded: "{sent_at}|{id}" of the oldest loaded message. */
export function beforeCursor(messages: ChatMessage[]): string | undefined {
  const oldest = messages[0];
  return oldest ? `${oldest.sent_at}|${oldest.id}` : undefined;
}

function chronological(a: ChatMessage, b: ChatMessage): number {
  return new Date(a.sent_at).getTime() - new Date(b.sent_at).getTime() || a.id.localeCompare(b.id);
}

/** Older pages plus the freshly polled newest page: deduped by id (the fresh copy wins), oldest first. */
export function mergeMessages(older: ChatMessage[], newest: ChatMessage[]): ChatMessage[] {
  const byId = new Map<string, ChatMessage>();
  for (const m of [...older, ...newest]) byId.set(m.id, m);
  return [...byId.values()].sort(chronological);
}

/** The name of the contact, or the raw WhatsApp number for an unknown sender. */
export function chatTitle(name: string | null, chatKey: string): string {
  return name?.trim() || chatKey;
}

const ROLE_LABELS: Partial<Record<PersonKind, string>> = {
  tenant: "Tenant",
  contractor: "Contractor",
  owner: "Owner",
};

export function roleLabel(kind: PersonKind | null): string | null {
  return (kind && ROLE_LABELS[kind]) || null;
}

/** Media links come from our own API; still never put a `javascript:` or `data:` URL into an href or src. */
export function isSafeMediaUrl(url: string): boolean {
  return /^https?:\/\//i.test(url) || (url.startsWith("/") && !url.startsWith("//"));
}

const dayNumber = (d: Date, tz: string): number => {
  const [y, m, day] = new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" })
    .format(d)
    .split("-")
    .map(Number);
  return Math.floor(Date.UTC(y, m - 1, day) / 86_400_000);
};

/** The time column of a chat row: the clock today, "Yesterday", the weekday within a week, else "2 Oct". */
export function listTime(iso: string, now: Date, tz: string): string {
  const at = new Date(iso);
  const age = dayNumber(now, tz) - dayNumber(at, tz);
  if (age <= 0) {
    return new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(at);
  }
  if (age === 1) return "Yesterday";
  if (age < 7) return new Intl.DateTimeFormat("en-GB", { timeZone: tz, weekday: "short" }).format(at);
  return new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "numeric", month: "short" }).format(at);
}

/** `?chat=` value to chat key. A raw `+` in a query string decodes to a space, so a leading space is the plus. */
export function chatKeyFromParam(raw: string | null): string | null {
  if (!raw) return null;
  return raw.startsWith(" ") ? `+${raw.slice(1)}` : raw;
}
