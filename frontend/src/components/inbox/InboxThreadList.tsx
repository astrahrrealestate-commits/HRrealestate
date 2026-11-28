"use client";

import React, { useMemo } from "react";
import { localDayNumber } from "@/lib/clock";
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
  checkedIds?: Set<string>;
  onToggleCheck?: (threadId: string) => void;
  onSelectThread: (threadId: string) => void;
  onDone?: (threadId: string) => void;
  onSnooze?: (threadId: string) => void;
  className?: string;
  /** When true, pin urgent threads to their own top section regardless of date. */
  groupByUrgency?: boolean;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  onLoadMore?: () => void;
}

interface ThreadGroup {
  id: string;
  label: string;
  threads: InboxThread[];
}

const MONTH_FORMATTER = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });

/**
 * InboxThreadList implements Section 5.2:
 * - Group headers (small, grey, sticky): Urgent (when grouping by urgency), Today, Yesterday, This Week, then Month Year.
 * - Flat list of ThreadRows, right border only, full height.
 * - Empty state: "All clear. Nothing needs you." with no illustration.
 */
export function InboxThreadList({
  threads,
  loadState = "ready",
  isFiltered = false,
  groupByUrgency = true,
  selectedThreadId,
  checkedIds,
  onToggleCheck,
  onSelectThread,
  onDone,
  onSnooze,
  className,
  hasMore = false,
  isLoadingMore = false,
  onLoadMore,
}: InboxThreadListProps) {
  // Group threads into Urgent (if urgency sort), Today, Yesterday, This Week, then Month Year
  const groupedThreads = useMemo(() => {
    const now = new Date();
    const todayDay = localDayNumber(now);
    const urgentGroup: InboxThread[] = [];
    const todayGroup: InboxThread[] = [];
    const yesterdayGroup: InboxThread[] = [];
    const weekGroup: InboxThread[] = [];
    const monthOrder: string[] = [];
    const monthBuckets = new Map<string, { label: string; threads: InboxThread[] }>();

    threads.forEach((t) => {
      if (groupByUrgency && isUrgent(t)) {
        urgentGroup.push(t);
        return;
      }

      const receivedDate = new Date(t.receivedAt);
      if (isNaN(receivedDate.getTime())) {
        const key = "earlier";
        if (!monthBuckets.has(key)) {
          monthBuckets.set(key, { label: "Earlier", threads: [] });
          monthOrder.push(key);
        }
        monthBuckets.get(key)!.threads.push(t);
        return;
      }

      const diff = todayDay - localDayNumber(receivedDate);
      if (diff === 0) {
        todayGroup.push(t);
      } else if (diff === 1) {
        yesterdayGroup.push(t);
      } else if (diff > 1 && diff < 7) {
        weekGroup.push(t);
      } else {
        const ym = `${receivedDate.getFullYear()}-${String(receivedDate.getMonth() + 1).padStart(2, "0")}`;
        if (!monthBuckets.has(ym)) {
          monthBuckets.set(ym, { label: MONTH_FORMATTER.format(receivedDate), threads: [] });
          monthOrder.push(ym);
        }
        monthBuckets.get(ym)!.threads.push(t);
      }
    });

    const groups: ThreadGroup[] = [
      { id: "urgent", label: "Urgent", threads: urgentGroup },
      { id: "today", label: "Today", threads: todayGroup },
      { id: "yesterday", label: "Yesterday", threads: yesterdayGroup },
      { id: "this_week", label: "This Week", threads: weekGroup },
      ...monthOrder.map((key) => ({ id: key, ...monthBuckets.get(key)! })),
    ];

    return groups.filter((g) => g.threads.length > 0);
  }, [threads, groupByUrgency]);

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
                roleLabel: t.recipientRoleDetail,
                category: t.category,
                status: needsAttention ? "needs_you" : "handled",
              };

              return (
                <ThreadRow
                  key={t.id}
                  t={rowItem}
                  selected={t.id === selectedThreadId}
                  checked={checkedIds?.has(t.id)}
                  onToggleCheck={onToggleCheck ? () => onToggleCheck(t.id) : undefined}
                  onSelect={() => onSelectThread(t.id)}
                  onDone={onDone ? () => onDone(t.id) : undefined}
                  onSnooze={onSnooze ? () => onSnooze(t.id) : undefined}
                />
              );
            })}
          </div>
        </div>
      ))}

      {hasMore && (
        <div className="p-3 border-t border-[var(--line)] bg-[var(--pane)] flex justify-center sticky bottom-0 z-10 shadow-xs">
          <button
            type="button"
            onClick={onLoadMore}
            disabled={isLoadingMore}
            className="w-full py-2 px-4 rounded-xl text-xs font-semibold bg-[var(--bg)] hover:bg-[var(--selected)] border border-[var(--line)] text-[var(--ink)] transition-colors flex items-center justify-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            {isLoadingMore ? "Loading more..." : "Load 20 More Threads"}
          </button>
        </div>
      )}
    </div>
  );
}
