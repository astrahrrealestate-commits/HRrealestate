"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { beforeCursor, mergeMessages, sameMessages } from "@/lib/chats";
import { getChatMessages } from "@/lib/chatsApi";
import { usePolling } from "@/hooks/usePolling";
import type { ChatMessage, ChatThread } from "@/types/chats";
import { useCachedState } from "@/hooks/useCachedState";

const POLL_MS = 8000;
const URL_REFRESH_MS = 120_000; // attachment links live 5 minutes: re-adopt a page at least this often
const PAGE = 100; // the API's default page size: a shorter first page means there is nothing older

export interface ChatThreadState {
  thread: ChatThread | null;
  /** True once this mount has fetched: a thread painted from the cache must not mark anything read. */
  fresh: boolean;
  messages: ChatMessage[];
  failed: boolean;
  hasOlder: boolean;
  loadingOlder: boolean;
  loadOlder: () => void;
}

/** One chat: the newest page polled every 8 s, older pages loaded on request. Mount it with `key={chatKey}`. */
export function useChatThread(chatKey: string): ChatThreadState {
  const [thread, setThread] = useCachedState<ChatThread | null>(`chats.thread.${chatKey}`, null);
  const [older, setOlder] = useState<ChatMessage[]>([]);
  const [failed, setFailed] = useState(false);
  const [startReached, setStartReached] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);

  const [fresh, setFresh] = useState(false);
  const shownOnScreen = useRef(true);
  useEffect(() => {
    shownOnScreen.current = true;
    return () => {
      shownOnScreen.current = false;
      setFresh(false);
    };
  }, []);

  const shown = useRef<{ thread: ChatThread; at: number } | null>(null);

  const refresh = useCallback(async () => {
    const res = await getChatMessages(chatKey);
    setFailed(res === null);
    if (!res) return;
    if (shownOnScreen.current) setFresh(true);
    const prev = shown.current;
    const unchanged =
      prev !== null &&
      Date.now() - prev.at < URL_REFRESH_MS &&
      prev.thread.name === res.name &&
      prev.thread.person_kind === res.person_kind &&
      prev.thread.case_id === res.case_id &&
      sameMessages(prev.thread.messages, res.messages);
    if (unchanged) return; // same data: keep the same objects so nothing below re-renders or re-scrolls
    shown.current = { thread: res, at: Date.now() };
    setThread(res);
  }, [chatKey, setThread]);
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
  return { thread, fresh, messages, failed, hasOlder, loadingOlder, loadOlder };
}
