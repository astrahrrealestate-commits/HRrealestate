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
  const heightBefore = useRef<number | null>(null);
  const days = useMemo(() => groupByDay(messages, APP_TIME_ZONE), [messages]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    if (heightBefore.current !== null) {
      el.scrollTop += el.scrollHeight - heightBefore.current;
      heightBefore.current = null;
    } else if (stick.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const loadOlder = () => {
    heightBefore.current = box.current?.scrollHeight ?? null;
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
        <section key={`${group.day}-${group.messages[0].id}`} className="space-y-1.5">
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
