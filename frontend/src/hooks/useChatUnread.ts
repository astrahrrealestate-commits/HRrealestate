"use client";

import { useCallback, useEffect, useState } from "react";
import { totalUnread } from "@/lib/chats";
import { getChats } from "@/lib/chatsApi";
import { usePolling } from "@/hooks/usePolling";

const CHATS_CHANGED = "estateos:chats-changed";
const POLL_MS = 8000;

/** Tells every `useChatUnread` (the sidebar) to look again now, e.g. after a chat was marked read. */
export function notifyChatsChanged(): void {
  window.dispatchEvent(new Event(CHATS_CHANGED));
}

/** Total unread WhatsApp messages across chats; 0 while unknown or when the API is unreachable. */
export function useChatUnread(): number {
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    const items = await getChats({ filter: "unread", limit: 100 });
    if (items) setUnread(totalUnread(items));
  }, []);

  usePolling(refresh, POLL_MS);

  useEffect(() => {
    const onChanged = () => void refresh();
    window.addEventListener(CHATS_CHANGED, onChanged);
    return () => window.removeEventListener(CHATS_CHANGED, onChanged);
  }, [refresh]);

  return unread;
}
