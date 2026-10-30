"use client";

import React from "react";
import { Check, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { Avatar } from "@/components/ui/Avatar";
import { formatListTime } from "@/lib/dateUtils";

export interface ThreadRowItem {
  id: string;
  contactName: string;
  channel?: "whatsapp" | "gmail" | "portal" | "phone" | string;
  unit: string;
  subject: string;
  snippet: string;
  hasDraft?: boolean;
  lastFromUs?: boolean;
  lastAt: Date | string;
  urgent?: boolean;
  waitingDays?: number;
  count?: number;
  isRead?: boolean;
  status: "needs_you" | "handled" | "waiting" | string;
}

export interface ThreadRowProps {
  t: ThreadRowItem;
  selected?: boolean;
  onSelect?: () => void;
  onDone?: (e: React.MouseEvent) => void;
  onSnooze?: (e: React.MouseEvent) => void;
  className?: string;
}

/**
 * ThreadRow implements Section 6.1 & Section 5.2:
 * - Line 1: contact name (bold if needs_you) + right: time (Section 3.5) or hover quick actions
 * - Line 2: unit and subject
 * - Line 3: snippet in grey with optional "✦ Draft ready ·" (orange) or "You: " prefix
 * - Right under time: "Urgent" or "Xd waiting" in --accent-ink, plus count if > 1
 * - 8px orange dot at row start for unanswered/needs_you
 * - Selected state: bg-[var(--selected)] + 2px ink left bar
 */
export function ThreadRow({
  t,
  selected = false,
  onSelect,
  onDone,
  onSnooze,
  className,
}: ThreadRowProps) {
  const isUnread = t.isRead === false || (t.isRead === undefined && t.status === "needs_you");
  const needsYou = t.status === "needs_you";
  const dateObj = t.lastAt instanceof Date ? t.lastAt : new Date(t.lastAt);
  const formattedTime = formatListTime(t.lastAt || dateObj);
  const isoTime = isNaN(dateObj.getTime()) ? "" : dateObj.toISOString();

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected}
      className={cn(
        "group grid w-full grid-cols-[8px_40px_1fr_auto] items-start gap-3 border-b border-[var(--line)] px-4 py-3 text-left transition-colors cursor-pointer relative focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
        // Gmail-style contrast: unread rows are elevated crisp pane with rich text, read rows are calm muted bg
        isUnread ? "bg-[var(--pane)]" : "bg-[var(--bg)]/60 text-[var(--ink-3)]",
        selected && "bg-[var(--selected)] shadow-[inset_2px_0_0_var(--ink)]",
        className
      )}
    >
      {/* 8px orange dot or unread dot */}
      <span
        className={cn(
          "mt-4 h-2 w-2 rounded-full flex-shrink-0 transition-colors",
          needsYou ? "bg-[var(--accent)]" : isUnread ? "bg-[var(--ink-2)]" : "bg-transparent"
        )}
      />

      {/* Avatar with tiny channel badge */}
      <Avatar name={t.contactName} channel={t.channel} />

      {/* Text column: Sender name, Flat/Address, Subject, Snippet */}
      <span className="min-w-0">
        <span
          className={cn(
            "block truncate text-[14.5px] leading-snug",
            isUnread ? "font-bold text-[var(--ink)]" : "font-normal text-[var(--ink-2)]"
          )}
        >
          {t.contactName}
        </span>

        <span className="block truncate text-sm leading-normal mt-0.5">
          {t.unit ? (
            <span className={cn("text-[var(--ink)]", isUnread ? "font-bold" : "font-semibold")}>{t.unit}</span>
          ) : null}
          {t.unit && t.subject ? (
            <span className="text-[var(--ink-3)] font-normal"> · </span>
          ) : null}
          <span className={isUnread ? "font-semibold text-[var(--ink)]" : "font-normal text-[var(--ink-2)]"}>
            {t.subject}
          </span>
        </span>

        <span className={cn("block truncate text-sm leading-normal", isUnread ? "text-[var(--ink-2)] font-medium" : "text-[var(--ink-3)]")}>
          {t.lastFromUs && "You: "}
          {t.snippet}
        </span>
      </span>

      {/* Time & urgency / waiting indicator */}
      <span className="flex flex-col items-end gap-1 whitespace-nowrap text-xs flex-shrink-0 pt-0.5">
        <time
          suppressHydrationWarning
          className={cn(
            "font-mono text-[12px]",
            isUnread ? "font-bold text-[var(--ink)]" : "font-medium text-[var(--ink-3)]"
          )}
          title={isoTime || formattedTime}
        >
          {formattedTime}
        </time>

        <div className="flex items-center gap-1.5">
          {/* Urgency label (orange text, no fill) */}
          {t.urgent && (
            <span className="font-semibold text-[var(--accent-ink)] text-xs">
              Urgent
            </span>
          )}

          {/* Waiting days indicator (orange text when >= 1 day) */}
          {!t.urgent && (t.waitingDays ?? 0) >= 1 && (
            <span className="text-[var(--accent-ink)] text-xs font-medium">
              {t.waitingDays}d waiting
            </span>
          )}

          {/* Quick hover actions: Done & Snooze (Section 5.2) */}
          {(onDone || onSnooze) && (
            <span className="hidden group-hover:inline-flex items-center gap-0.5 -mr-1">
              {onDone && (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    onDone(e);
                  }}
                  title="Mark as done"
                  className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
                >
                  <Check className="w-3.5 h-3.5" />
                </span>
              )}
              {onSnooze && (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSnooze(e);
                  }}
                  title="Snooze"
                  className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
                >
                  <Clock className="w-3.5 h-3.5" />
                </span>
              )}
            </span>
          )}

          {/* Thread message count if over 1 */}
          {(t.count ?? 1) > 1 && (
            <span className="text-[var(--ink-3)] text-xs tabular-nums">
              {t.count}
            </span>
          )}
        </div>
      </span>
    </button>
  );
}
