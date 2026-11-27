"use client";

import { BACKEND_BASE_URL } from "@/lib/backend";

export const FEED_EVENT = "estateos:feed-event";
const SSE_FALLBACK_POLL_MS = 60_000;

let source: EventSource | null = null;
let connected = false;
let refCount = 0;

function emitFeedEvent(kind: string): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(FEED_EVENT, { detail: { kind } }));
}

export function isFeedStreamConnected(): boolean {
  return connected;
}

export function effectivePollInterval(intervalMs: number): number {
  return connected ? Math.max(intervalMs, SSE_FALLBACK_POLL_MS) : intervalMs;
}

export function subscribeFeedEvents(): () => void {
  if (typeof window === "undefined" || typeof EventSource === "undefined") {
    return () => {};
  }
  refCount += 1;
  if (source === null) {
    const url = `${BACKEND_BASE_URL}/api/v1/events`;
    source = new EventSource(url, { withCredentials: true });
    source.onopen = () => {
      connected = true;
    };
    source.onerror = () => {
      connected = false;
    };
    source.addEventListener("feed", () => emitFeedEvent("feed"));
    source.addEventListener("turn", () => emitFeedEvent("turn"));
  }
  return () => {
    refCount = Math.max(0, refCount - 1);
    if (refCount === 0 && source !== null) {
      source.close();
      source = null;
      connected = false;
    }
  };
}
