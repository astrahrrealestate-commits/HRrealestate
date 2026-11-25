/** Pure helpers of the Chats page (no React, no I/O). */

import { APP_TIME_ZONE, localDayNumber } from "@/lib/clock";
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

const INLINE_IMAGES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

/** Only these are drawn in an <img>; every other file type (svg included) is a download chip. */
export function isInlineImage(mime: string): boolean {
  return INLINE_IMAGES.has(mime.split(";")[0].trim().toLowerCase());
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

/** The tick of an outbound message. A clock only while our own send is in flight (`pending`); a row with no delivery
 * status that is not pending (a Business-app echo, an old row) is neutrally "sent". */
export function tickFromStatus(status: DeliveryStatus | null, pending = false): Tick {
  if (status === "failed") return "failed";
  if (pending) return "pending";
  return status ?? "sent";
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

/** The time column of a chat row: the clock today, "Yesterday", the weekday within a week, else "2 Oct". */
export function listTime(iso: string, now: Date): string {
  const at = new Date(iso);
  const tz = APP_TIME_ZONE;
  const age = localDayNumber(now) - localDayNumber(at);
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

/** Whether a polled page holds the same messages as the one already shown. Attachment URLs are ignored: they are
 * signed anew on every request, so comparing them would call every page with a file in it changed. */
export function sameMessages(a: ChatMessage[], b: ChatMessage[]): boolean {
  return (
    a.length === b.length &&
    a.every((x, i) => {
      const y = b[i];
      return (
        x.id === y.id &&
        x.text === y.text &&
        x.delivery_status === y.delivery_status &&
        x.pending === y.pending &&
        x.error === y.error &&
        x.suspicious === y.suspicious &&
        x.suspicious_reason === y.suspicious_reason &&
        x.reply_to?.id === y.reply_to?.id &&
        x.attachments.map((f) => f.id).join() === y.attachments.map((f) => f.id).join()
      );
    })
  );
}
