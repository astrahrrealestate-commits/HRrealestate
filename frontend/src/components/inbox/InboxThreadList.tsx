"use client";

import React, { useMemo } from "react";
import { differenceInCalendarDays } from "date-fns";
import { InboxThread } from "@/types/inbox";
import { ThreadRow, ThreadRowItem } from "@/components/ui/ThreadRow";
import { isUrgent, isNeedsYou } from "@/lib/selectors";
import { cn } from "@/lib/utils";

interface InboxThreadListProps {
  threads: InboxThread[];
  /** Until the first load answers, or after it failed with nothing to show, an empty list must not read "All clear". */
  loadState?: "loading" | "ready" | "error";
  /** The list is empty because of a search, a filter or a tab, not because the inbox is. */
  isFiltered?: boolean;
  selectedThreadId: string;
  onSelectThread: (threadId: string) => void;
  onDone?: (threadId: string) => void;
  onSnooze?: (threadId: string) => void;
  className?: string;
}

interface ThreadGroup {
  id: "urgent" | "today" | "yesterday" | "earlier";
  label: string;
  threads: InboxThread[];
}

/**
 * InboxThreadList implements Section 5.2:
 * - Group headers (small, grey, sticky): Urgent, Today, Yesterday, Earlier. Only show groups with items.
 * - Flat list of ThreadRows, right border only, full height.
 * - Empty state: "All clear. Nothing needs you." with no illustration.
 */
export function InboxThreadList({
  threads,
  loadState = "ready",
  isFiltered = false,
  selectedThreadId,
  onSelectThread,
  onDone,
  onSnooze,
  className,
}: InboxThreadListProps) {
  // Group threads into Urgent, Today, Yesterday, Earlier
  const groupedThreads = useMemo(() => {
    const now = new Date();
    const urgentGroup: InboxThread[] = [];
    const todayGroup: InboxThread[] = [];
    const yesterdayGroup: InboxThread[] = [];
    const earlierGroup: InboxThread[] = [];

    threads.forEach((t) => {
      // 1. Check if thread is Urgent
      if (isUrgent(t)) {
        urgentGroup.push(t);
        return;
      }

      // 2. Otherwise group by calendar day difference
      const receivedDate = new Date(t.receivedAt);
      const diff = isNaN(receivedDate.getTime())
        ? 0
        : differenceInCalendarDays(now, receivedDate);

      if (diff === 0) {
        todayGroup.push(t);
      } else if (diff === 1) {
        yesterdayGroup.push(t);
      } else {
        earlierGroup.push(t);
      }
    });

    const groups: ThreadGroup[] = [
      { id: "urgent", label: "Urgent", threads: urgentGroup },
      { id: "today", label: "Today", threads: todayGroup },
      { id: "yesterday", label: "Yesterday", threads: yesterdayGroup },
      { id: "earlier", label: "Earlier", threads: earlierGroup },
    ];

    // Filter out groups with 0 items
    return groups.filter((g) => g.threads.length > 0);
  }, [threads]);

  if (threads.length === 0) {
    return (
      <div
        className={cn(
          "w-full h-full flex flex-col items-center justify-center p-8 text-center bg-[var(--pane)] border-r border-[var(--line)]",
          className
        )}
      >
        <p className="text-[14px] text-[var(--ink-2)] font-medium" role={loadState === "error" ? "alert" : "status"}>
          {loadState === "loading"
            ? "Loading your inbox…"
            : loadState === "error"
              ? "Can't reach the server. Retrying…"
              : isFiltered
                ? "No threads match."
                : "All clear. Nothing needs you."}
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "w-full h-full overflow-y-auto bg-[var(--pane)] border-r border-[var(--line)] flex flex-col",
        className
      )}
    >
      {groupedThreads.map((group) => (
        <div key={group.id} className="relative">
          {/* Sticky Group Header (Section 5.2) */}
          <div className="sticky top-0 z-10 px-4 py-1.5 bg-[var(--bg)]/90 backdrop-blur-xs border-b border-[var(--line)] text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] flex items-center justify-between">
            <span className={group.id === "urgent" ? "text-[var(--accent-ink)]" : ""}>
              {group.label}
            </span>
            <span className="font-mono tabular-nums">{group.threads.length}</span>
          </div>

          {/* Grouped Thread Rows */}
          <div className="divide-y divide-[var(--line)]">
            {group.threads.map((t) => {
              const needsAttention = isNeedsYou(t);
              const rowItem: ThreadRowItem = {
                id: t.id,
                contactName: t.senderName,
                channel: t.channel,
                unit: t.unitLabel,
                subject: t.subject || t.issueTitle || t.caseRef,
                snippet: t.latestSnippet,
                hasDraft: Boolean(t.draftProposal?.drafts?.length || t.draftProposal?.whatsappDrafts?.length || t.draftProposal?.gmailDrafts?.length),
                lastFromUs: (t.messages && t.messages.length > 0)
                  ? t.messages[t.messages.length - 1].sender === "owner"
                  : false,
                lastAt: t.receivedAt,
                urgent: isUrgent(t),
                count: t.messages?.length || 1,
                isRead: t.isRead,
                status: needsAttention ? "needs_you" : "handled",
              };

              return (
                <ThreadRow
                  key={t.id}
                  t={rowItem}
                  selected={t.id === selectedThreadId}
                  onSelect={() => onSelectThread(t.id)}
                  onDone={onDone ? () => onDone(t.id) : undefined}
                  onSnooze={onSnooze ? () => onSnooze(t.id) : undefined}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
