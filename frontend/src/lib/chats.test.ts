import { describe, expect, it } from "vitest";
import type { ChatItem, ChatMessage } from "@/types/chats";
import {
  beforeCursor,
  chatKeyFromParam,
  chatPreview,
  chatTitle,
  groupByDay,
  isInlineImage,
  isSafeMediaUrl,
  listTime,
  mergeMessages,
  roleLabel,
  sameMessages,
  tickFromStatus,
  tickFor,
  totalUnread,
} from "@/lib/chats";

const TZ = "Europe/Amsterdam";

function item(over: Partial<ChatItem> = {}): ChatItem {
  return {
    chat_key: "+31612345678",
    name: "Mrs. de Vries",
    person_kind: "tenant",
    last_message_id: "m1",
    last_at: "2026-11-23T09:12:00+00:00",
    last_text: "Pump is leaking",
    last_kind: "text",
    last_direction: "inbound",
    last_delivery: null,
    last_pending: false,
    unread: 0,
    cursor: "2026-11-23T09:12:00+00:00|m1",
    ...over,
  };
}

function msg(over: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "a",
    direction: "outbound",
    sent_at: "2026-11-23T09:12:00+00:00",
    text: "hi",
    kind: "text",
    delivery_status: null,
    error: null,
    suspicious: false,
    suspicious_reason: null,
    reply_to: null,
    attachments: [],
    pending: false,
    ...over,
  };
}

describe("chatPreview", () => {
  it("shows the text", () => {
    expect(chatPreview(item())).toBe("Pump is leaking");
  });
  it("names the media kind when there is no text", () => {
    expect(chatPreview(item({ last_text: "", last_kind: "audio" }))).toBe("Voice message");
    expect(chatPreview(item({ last_text: "", last_kind: "image" }))).toBe("Photo");
    expect(chatPreview(item({ last_text: "", last_kind: "document" }))).toBe("Document");
    expect(chatPreview(item({ last_text: "  ", last_kind: "sticker" }))).toBe("Message");
    expect(chatPreview(item({ last_text: "", last_kind: null }))).toBe("Message");
  });
  it("prefixes outbound with You", () => {
    expect(chatPreview(item({ last_direction: "outbound", last_text: "Ok" }))).toBe("You: Ok");
    expect(chatPreview(item({ last_direction: "outbound", last_text: "", last_kind: "image" }))).toBe(
      "You: Photo"
    );
  });
});

describe("groupByDay", () => {
  it("splits at local midnight in the given zone and keeps order", () => {
    // 22:30Z = 23:30 Amsterdam (CET), 23:30Z = 00:30 the next local day
    const a = msg({ id: "a", sent_at: "2026-11-23T22:30:00+00:00" });
    const b = msg({ id: "b", sent_at: "2026-11-23T23:30:00+00:00" });
    const c = msg({ id: "c", sent_at: "2026-11-24T08:00:00+00:00" });
    const groups = groupByDay([a, b, c], TZ);
    expect(groups.map((g) => g.messages.map((m) => m.id))).toEqual([["a"], ["b", "c"]]);
    expect(groups[0].day).toBe("Mon 23 Nov");
    expect(groups[1].day).toBe("Tue 24 Nov");
  });
  it("is empty for no messages", () => {
    expect(groupByDay([], TZ)).toEqual([]);
  });
});

describe("tickFor", () => {
  it("is pending only for a message our own send path has not confirmed yet", () => {
    expect(tickFor(msg({ pending: true }))).toBe("pending");
  });
  it("shows a neutral sent tick for an outbound row with no status that is not pending (echo, old row)", () => {
    expect(tickFor(msg())).toBe("sent");
    expect(tickFromStatus(null)).toBe("sent");
    expect(tickFromStatus(null, false)).toBe("sent");
    expect(tickFromStatus(null, true)).toBe("pending");
    expect(tickFromStatus("read", true)).toBe("pending");
  });
  it("maps the delivery status", () => {
    expect(tickFor(msg({ delivery_status: "sent" }))).toBe("sent");
    expect(tickFor(msg({ delivery_status: "delivered" }))).toBe("delivered");
    expect(tickFor(msg({ delivery_status: "read" }))).toBe("read");
    expect(tickFor(msg({ delivery_status: "failed" }))).toBe("failed");
  });
});

describe("totalUnread", () => {
  it("sums the unread counts", () => {
    expect(totalUnread([item({ unread: 2 }), item({ unread: 0 }), item({ unread: 3 })])).toBe(5);
    expect(totalUnread([])).toBe(0);
  });
});

describe("beforeCursor", () => {
  it("is sent_at|id of the oldest loaded message", () => {
    const first = msg({ id: "x", sent_at: "2026-11-23T09:12:00+00:00" });
    expect(beforeCursor([first, msg({ id: "y" })])).toBe("2026-11-23T09:12:00+00:00|x");
    expect(beforeCursor([])).toBeUndefined();
  });
});

describe("mergeMessages", () => {
  it("joins older pages with the polled newest page, deduped and oldest first", () => {
    const old = msg({ id: "1", sent_at: "2026-11-22T10:00:00+00:00" });
    const mid = msg({ id: "2", sent_at: "2026-11-23T10:00:00+00:00", text: "stale" });
    const midFresh = msg({ id: "2", sent_at: "2026-11-23T10:00:00+00:00", text: "fresh" });
    const last = msg({ id: "3", sent_at: "2026-11-23T11:00:00+00:00" });
    const merged = mergeMessages([old, mid], [midFresh, last]);
    expect(merged.map((m) => m.id)).toEqual(["1", "2", "3"]);
    expect(merged[1].text).toBe("fresh");
  });
});

describe("chatTitle and roleLabel", () => {
  it("falls back to the number for an unknown sender", () => {
    expect(chatTitle("Mrs. de Vries", "+31612345678")).toBe("Mrs. de Vries");
    expect(chatTitle(null, "+31612345678")).toBe("+31612345678");
    expect(chatTitle("  ", "+31612345678")).toBe("+31612345678");
  });
  it("names the roles worth a tag", () => {
    expect(roleLabel("tenant")).toBe("Tenant");
    expect(roleLabel("contractor")).toBe("Contractor");
    expect(roleLabel("owner")).toBe("Owner");
    expect(roleLabel("other")).toBeNull();
    expect(roleLabel(null)).toBeNull();
  });
});

describe("isSafeMediaUrl", () => {
  it("allows http(s) and site-relative links only", () => {
    expect(isSafeMediaUrl("https://bucket.s3.eu-north-1.amazonaws.com/a.jpg?X-Amz-Signature=1")).toBe(true);
    expect(isSafeMediaUrl("http://localhost:9000/a.jpg")).toBe(true);
    expect(isSafeMediaUrl("/media/a.jpg")).toBe(true);
    expect(isSafeMediaUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeMediaUrl("data:text/html,<b>x</b>")).toBe(false);
    expect(isSafeMediaUrl("//evil.example/a.jpg")).toBe(false);
    expect(isSafeMediaUrl("")).toBe(false);
  });
});

describe("listTime", () => {
  const now = new Date("2026-11-24T12:00:00+00:00");
  it("shows the clock for today, the weekday within a week, else the date", () => {
    expect(listTime("2026-11-24T08:05:00+00:00", now)).toBe("09:05");
    expect(listTime("2026-11-23T08:05:00+00:00", now)).toBe("Yesterday");
    expect(listTime("2026-11-20T08:05:00+00:00", now)).toBe("Fri");
    expect(listTime("2026-10-02T08:05:00+00:00", now)).toBe("2 Oct");
  });
  it("uses the local day, not UTC", () => {
    expect(listTime("2026-11-23T23:30:00+00:00", now)).toBe("00:30");
  });
});

describe("chatKeyFromParam", () => {
  it("restores the plus that a raw query string turned into a space", () => {
    expect(chatKeyFromParam("+31612345678")).toBe("+31612345678");
    expect(chatKeyFromParam(" 31612345678")).toBe("+31612345678");
    expect(chatKeyFromParam(null)).toBeNull();
    expect(chatKeyFromParam("")).toBeNull();
  });
});

describe("isInlineImage", () => {
  it("shows only raster types a browser renders without running anything", () => {
    for (const ok of ["image/png", "image/jpeg", "image/gif", "image/webp", "IMAGE/PNG; q=1"]) {
      expect(isInlineImage(ok)).toBe(true);
    }
    for (const bad of ["image/svg+xml", "image/x-icon", "image/tiff", "text/html", "application/pdf", ""]) {
      expect(isInlineImage(bad)).toBe(false);
    }
  });
});

describe("sameMessages", () => {
  const att = (url: string) => ({ id: "f", filename: "a.jpg", mime_type: "image/jpeg", size_bytes: 3, url });
  it("is true for the same messages even though the presigned URLs were re-signed", () => {
    const a = [msg({ id: "1", attachments: [att("https://s3/x?sig=1")] }), msg({ id: "2" })];
    const b = [msg({ id: "1", attachments: [att("https://s3/x?sig=2")] }), msg({ id: "2" })];
    expect(sameMessages(a, b)).toBe(true);
  });
  it("notices a new message, a status change, a text change or a different flag", () => {
    const base = [msg({ id: "1" })];
    expect(sameMessages(base, [...base, msg({ id: "2" })])).toBe(false);
    expect(sameMessages(base, [msg({ id: "1", delivery_status: "read" })])).toBe(false);
    expect(sameMessages(base, [msg({ id: "1", text: "edited" })])).toBe(false);
    expect(sameMessages(base, [msg({ id: "1", suspicious: true })])).toBe(false);
    expect(sameMessages(base, [msg({ id: "1", attachments: [att("u")] })])).toBe(false);
  });
});
