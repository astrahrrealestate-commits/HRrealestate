"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { totalUnread } from "@/lib/chats";
import { getChats } from "@/lib/chatsApi";
import { usePolling } from "@/hooks/usePolling";

const CHATS_CHANGED = "estateos:chats-changed";
const POLL_MS = 8000;

/** Tells every `useChatUnread` (the sidebar) to look again now, e.g. after a chat was marked read. */
export function notifyChatsChanged(): void {
  window.dispatchEvent(new Event(CHATS_CHANGED));
}

/** Total unread WhatsApp messages across chats; 0 while unknown or when the API is unreachable. Does not ask the API
 * at all for a profile without the `inbox` section (it would answer 403 every time). */
export function useChatUnread(): number {
  const { canAccess } = useAuth();
  const enabled = canAccess("inbox");
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    const items = await getChats({ filter: "unread", limit: 100 });
    if (items) setUnread(totalUnread(items));
  }, []);

  usePolling(refresh, POLL_MS, { enabled });

  useEffect(() => {
    if (!enabled) return;
    const onChanged = () => void refresh();
    window.addEventListener(CHATS_CHANGED, onChanged);
    return () => window.removeEventListener(CHATS_CHANGED, onChanged);
  }, [enabled, refresh]);

  return enabled ? unread : 0;
}
