/** Chats API client: GET /api/chats, GET /api/chats/{key}/messages, POST /api/chats/{key}/read.
 * `null` / `false` means the request failed or was refused (the page shows an error, never invented data). */

import { BACKEND_BASE_URL, apiFetch } from "@/lib/backend";
import type { ChatFilter, ChatItem, ChatThread } from "@/types/chats";

const TIMEOUT_MS = 10000;

export interface ChatListParams {
  filter?: ChatFilter;
  q?: string;
  before?: string;
  limit?: number;
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

const chatPath = (chatKey: string) => `/api/chats/${encodeURIComponent(chatKey)}`;

export function getChats(params: ChatListParams = {}): Promise<ChatItem[] | null> {
  const query = new URLSearchParams();
  if (params.filter && params.filter !== "all") query.set("filter", params.filter);
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.before) query.set("before", params.before);
  if (params.limit) query.set("limit", String(params.limit));
  const qs = query.toString();
  return getJson<ChatItem[]>(`/api/chats${qs ? `?${qs}` : ""}`);
}

export function getChatMessages(chatKey: string, before?: string): Promise<ChatThread | null> {
  const qs = before ? `?${new URLSearchParams({ before })}` : "";
  return getJson<ChatThread>(`${chatPath(chatKey)}/messages${qs}`);
}

export async function markChatRead(chatKey: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}${chatPath(chatKey)}/read`, {
      method: "POST",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    return res.ok;
  } catch {
    return false;
  }
}
