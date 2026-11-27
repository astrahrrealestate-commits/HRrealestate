"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getChats } from "@/lib/chatsApi";
import { usePolling } from "@/hooks/usePolling";
import type { ChatFilter, ChatItem } from "@/types/chats";
import { useCachedState } from "@/hooks/useCachedState";

const POLL_MS = 8000;
const PAGE = 50;
const DEBOUNCE_MS = 300;

interface Pages {
  key: string;
  first: ChatItem[];
  extra: ChatItem[];
  extraDone: boolean;
}

const tailOf = (items: ChatItem[]) => items[items.length - 1]?.chat_key;

/** A polled first page. Older pages loaded earlier are kept only while the first page still ends at the same chat:
 * once it shifted (a chat from further down moved up), the old pages would leave a gap, so they are dropped. */
function nextPages(prev: Pages | null, key: string, first: ChatItem[]): Pages {
  const keep = prev?.key === key && tailOf(prev.first) === tailOf(first);
  return { key, first, extra: keep ? prev.extra : [], extraDone: keep && prev.extraDone };
}

export interface ChatListState {
  items: ChatItem[] | null;
  failed: boolean;
  hasMore: boolean;
  loadMore: () => void;
  refresh: () => Promise<void>;
}

/** The chat list for a filter and search text: newest page polled every 8 s, older pages added on request. */
export function useChatList(filter: ChatFilter, query: string): ChatListState {
  const [q, setQ] = useState(query);
  const [pages, setPages] = useCachedState<Pages | null>("chats.list", null);
  const [failed, setFailed] = useState(false);
  const key = `${filter}|${q.trim()}`;
  const current = useRef(key);

  useEffect(() => {
    current.current = key;
  });
  useEffect(() => {
    const timer = setTimeout(() => setQ(query), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const refresh = useCallback(async () => {
    const res = await getChats({ filter, q, limit: PAGE });
    if (current.current !== key) return;
    setFailed(res === null);
    if (res) setPages((p) => nextPages(p, key, res));
  }, [filter, q, key, setPages]);

  usePolling(refresh, POLL_MS, { restartKey: key });

  const live = pages?.key === key ? pages : null;
  const loadMore = useCallback(() => {
    if (!live) return;
    const all = [...live.first, ...live.extra];
    const before = all[all.length - 1]?.cursor;
    void getChats({ filter, q, before, limit: PAGE }).then((res) => {
      if (!res || current.current !== key) return;
      setPages((p) => (p?.key === key ? { ...p, extra: [...p.extra, ...res], extraDone: res.length < PAGE } : p));
    });
  }, [live, filter, q, key, setPages]);

  const seen = new Set(live?.first.map((c) => c.chat_key));
  const items = live ? [...live.first, ...live.extra.filter((c) => !seen.has(c.chat_key))] : null;
  const hasMore = !!live && live.first.length >= PAGE && !live.extraDone;
  return { items, failed, hasMore, loadMore, refresh };
}
