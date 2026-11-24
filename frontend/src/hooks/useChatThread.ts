"use client";

import { useCallback, useMemo, useState } from "react";
import { beforeCursor, mergeMessages } from "@/lib/chats";
import { getChatMessages } from "@/lib/chatsApi";
import { usePolling } from "@/hooks/usePolling";
import type { ChatMessage, ChatThread } from "@/types/chats";

const POLL_MS = 8000;
const PAGE = 100; // the API's default page size: a shorter first page means there is nothing older

export interface ChatThreadState {
  thread: ChatThread | null;
  messages: ChatMessage[];
  failed: boolean;
  hasOlder: boolean;
  loadingOlder: boolean;
  loadOlder: () => void;
}

/** One chat: the newest page polled every 8 s, older pages loaded on request. Mount it with `key={chatKey}`. */
export function useChatThread(chatKey: string): ChatThreadState {
  const [thread, setThread] = useState<ChatThread | null>(null);
  const [older, setOlder] = useState<ChatMessage[]>([]);
  const [failed, setFailed] = useState(false);
  const [startReached, setStartReached] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const refresh = useCallback(async () => {
    const res = await getChatMessages(chatKey);
    setFailed(res === null);
    if (res) setThread(res);
  }, [chatKey]);
  usePolling(refresh, POLL_MS);

  const messages = useMemo(() => mergeMessages(older, thread?.messages ?? []), [older, thread]);

  const loadOlder = useCallback(() => {
    const before = beforeCursor(messages);
    if (!before || loadingOlder) return;
    setLoadingOlder(true);
    void getChatMessages(chatKey, before)
      .then((res) => {
        if (!res) return setFailed(true);
        setOlder((o) => mergeMessages(o, res.messages));
        if (res.messages.length < PAGE) setStartReached(true);
      })
      .finally(() => setLoadingOlder(false));
  }, [chatKey, messages, loadingOlder]);

  const hasOlder = !!thread && !startReached && thread.messages.length >= PAGE;
  return { thread, messages, failed, hasOlder, loadingOlder, loadOlder };
}
