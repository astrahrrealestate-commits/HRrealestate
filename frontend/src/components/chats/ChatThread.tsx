"use client";

import { useLayoutEffect, useMemo, useRef } from "react";
import { APP_TIME_ZONE } from "@/lib/clock";
import { groupByDay } from "@/lib/chats";
import type { ChatMessage } from "@/types/chats";
import { MessageBubble } from "@/components/chats/MessageBubble";

const NEAR_BOTTOM_PX = 120;

interface ChatThreadProps {
  messages: ChatMessage[];
  hasOlder: boolean;
  loadingOlder: boolean;
  onLoadOlder: () => void;
}

/** The scrolling message list: day separators, bubbles, "Load older". Stays on the newest message unless he scrolled
 * up, and keeps his place when older messages are added above. */
export function ChatThread({ messages, hasOlder, loadingOlder, onLoadOlder }: ChatThreadProps) {
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  // Set when "Load older" is clicked; kept until that older page is really in (the oldest message changed), however
  // many polls arrive meanwhile, so his place is restored exactly once.
  const anchor = useRef<{ height: number; oldestId: string | undefined } | null>(null);
  const days = useMemo(() => groupByDay(messages, APP_TIME_ZONE), [messages]);
  const oldestId = messages[0]?.id;

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const waiting = anchor.current;
    if (waiting && oldestId !== waiting.oldestId) {
      el.scrollTop += el.scrollHeight - waiting.height;
      anchor.current = null;
      return;
    }
    if (waiting && loadingOlder) return; // the older page is still on its way: do not jump to the newest
    anchor.current = null; // the request ended without adding anything
    if (stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, oldestId, loadingOlder]);

  const loadOlder = () => {
    anchor.current = { height: box.current?.scrollHeight ?? 0, oldestId };
    onLoadOlder();
  };

  return (
    <div
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget;
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
      }}
      className="flex-1 min-h-0 overflow-y-auto bg-[var(--bg)] px-3 md:px-6 py-3 space-y-2"
    >
      {hasOlder && (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={loadOlder}
            disabled={loadingOlder}
            className="rounded-full border border-[var(--line)] bg-white px-3 py-1 text-xs font-medium text-[var(--ink-2)] hover:bg-[var(--selected)] disabled:opacity-60 cursor-pointer"
          >
            {loadingOlder ? "Loading..." : "Load older messages"}
          </button>
        </div>
      )}
      {days.map((group) => (
        <section key={group.day} className="space-y-1.5">
          <div className="flex justify-center py-1">
            <span className="rounded-full bg-white/80 border border-[var(--line)] px-3 py-0.5 text-[11px] font-medium text-[var(--ink-3)]">
              {group.day}
            </span>
          </div>
          {group.messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
        </section>
      ))}
    </div>
  );
}
