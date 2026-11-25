"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useAuth } from "@/context/AuthContext";
import { totalUnread } from "@/lib/chats";
import { getChats } from "@/lib/chatsApi";

const CHATS_CHANGED = "estateos:chats-changed";
const POLL_MS = 8000;

type UnreadListener = (count: number) => void;

const listeners = new Set<UnreadListener>();
let sharedUnread = 0;
let inFlight: Promise<void> | null = null;
let pollTimer: ReturnType<typeof setInterval> | null = null;
let lastFetchedAt = 0;
let globalListenersAttached = false;

async function fetchSharedUnread(force = false): Promise<void> {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
  if (!force && inFlight) return inFlight;
  if (!force && Date.now() - lastFetchedAt < 1500) return;
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const items = await getChats({ filter: "unread", limit: 100 });
      lastFetchedAt = Date.now();
      if (items) {
        const next = totalUnread(items);
        if (next !== sharedUnread) {
          sharedUnread = next;
          listeners.forEach((fn) => fn(next));
        }
      }
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

function handleVisibilityOrChanged() {
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
  if (listeners.size > 0) void fetchSharedUnread(true);
}

function ensureStoreStarted() {
  if (pollTimer === null) {
    pollTimer = setInterval(() => {
      if (listeners.size > 0) void fetchSharedUnread();
    }, POLL_MS);
  }
  if (!globalListenersAttached && typeof window !== "undefined") {
    globalListenersAttached = true;
    window.addEventListener(CHATS_CHANGED, handleVisibilityOrChanged);
    document.addEventListener("visibilitychange", handleVisibilityOrChanged);
  }
}

function stopStoreIfIdle() {
  if (listeners.size > 0) return;
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (globalListenersAttached && typeof window !== "undefined") {
    globalListenersAttached = false;
    window.removeEventListener(CHATS_CHANGED, handleVisibilityOrChanged);
    document.removeEventListener("visibilitychange", handleVisibilityOrChanged);
  }
}

/** Tells the shared unread store to refresh now (e.g. after a chat was marked read). */
export function notifyChatsChanged(): void {
  window.dispatchEvent(new Event(CHATS_CHANGED));
}

function subscribe(listener: UnreadListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): number {
  return sharedUnread;
}

function getServerSnapshot(): number {
  return 0;
}

/** Shared unread WhatsApp count across mounted sidebars/drawers using one deduplicated 8s poll. */
export function useChatUnread(): number {
  const { canAccess } = useAuth();
  const enabled = canAccess("inbox");
  const unread = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    if (!enabled) return;
    ensureStoreStarted();
    void fetchSharedUnread();
    return () => {
      stopStoreIfIdle();
    };
  }, [enabled]);

  return enabled ? unread : 0;
}
