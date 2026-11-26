"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Building2, Calendar, Clock, Mail, MessageSquare, Sparkles, UserPlus } from "lucide-react";
import { cn } from "@/lib/utils";
import { CategoryBucket, DashboardItem } from "@/lib/dashboardCategories";

interface CategoryActionListProps {
  bucket: CategoryBucket;
  isLoading?: boolean;
  onSelectItem: (item: DashboardItem) => void;
}

const DEFAULT_VISIBLE = 12;

function ChannelGlyph({ channel }: { channel?: string }) {
  const ch = (channel || "").toLowerCase();
  if (ch === "whatsapp") {
    return <MessageSquare className="w-3.5 h-3.5 text-[#25D366] shrink-0" aria-label="WhatsApp" />;
  }
  if (ch === "gmail") {
    return <Mail className="w-3.5 h-3.5 text-[#EA4335] shrink-0" aria-label="Email" />;
  }
  if (ch === "brixx") {
    return <Building2 className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" aria-label="BRIXX" />;
  }
  if (ch === "calendar") {
    return <Calendar className="w-3.5 h-3.5 text-[var(--accent-ink)] shrink-0" aria-label="Calendar" />;
  }
  if (ch === "radar") {
    return <Clock className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" aria-label="Waiting" />;
  }
  return <UserPlus className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" aria-label="Lead" />;
}

function DashboardListRow({
  item,
  onSelect,
}: {
  item: DashboardItem;
  onSelect: (item: DashboardItem) => void;
}) {
  const isUrgentItem = item.group === "urgent";

  return (
    <button
      type="button"
      onClick={() => onSelect(item)}
      className={cn(
        "w-full text-left px-3.5 sm:px-5 py-3 flex items-start gap-3 transition-colors cursor-pointer group",
        "hover:bg-[var(--selected)]/50 focus:outline-none focus-visible:bg-[var(--selected)]",
        item.isUnread ? "bg-[var(--pane)]" : "bg-[var(--bg)]/35"
      )}
    >
      {/* Minimal status dot */}
      <span className="mt-2 w-2 shrink-0 flex items-center justify-center">
        {isUrgentItem ? (
          <span className="w-2 h-2 rounded-full bg-[#E14D12]" title="Urgent" />
        ) : item.isUnread ? (
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" title="Needs attention" />
        ) : null}
      </span>

      {/* Two-line main content */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <span
            className={cn(
              "text-[14px] truncate",
              item.isUnread || isUrgentItem
                ? "font-semibold text-[var(--ink)]"
                : "font-medium text-[var(--ink-2)]"
            )}
          >
            {item.partyName}
          </span>
          {item.unitLabel && (
            <>
              <span className="text-[var(--ink-3)] shrink-0">·</span>
              <span className="text-[13px] text-[var(--ink-2)] truncate">{item.unitLabel}</span>
            </>
          )}
          <span className="shrink-0 inline-flex items-center ml-0.5">
            <ChannelGlyph channel={item.channel} />
          </span>
        </div>

        <p className="text-[13px] text-[var(--ink-2)] truncate mt-0.5 leading-snug">
          <span className={cn(item.isUnread || isUrgentItem ? "text-[var(--ink)] font-medium" : "text-[var(--ink-2)]")}>
            {item.title}
          </span>
          {item.subtitle && item.subtitle !== item.title ? (
            <span className="text-[var(--ink-3)] font-normal"> — {item.subtitle}</span>
          ) : null}
        </p>
      </div>

      {/* Clean right metadata (no action buttons) */}
      <div className="shrink-0 text-right flex flex-col items-end gap-0.5 pl-2">
        <span
          className={cn(
            "text-[11.5px] font-mono tabular-nums whitespace-nowrap",
            isUrgentItem ? "text-[#B93C00] font-semibold" : "text-[var(--ink-3)]"
          )}
        >
          {item.timeLabel}
        </span>
        {item.hasDraft ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--accent-ink)] whitespace-nowrap">
            <Sparkles className="w-2.5 h-2.5 text-[var(--accent)]" />
            <span>Draft</span>
          </span>
        ) : item.secondaryTag ? (
          <span className="text-[11px] text-[var(--ink-3)] whitespace-nowrap">
            {item.secondaryTag}
          </span>
        ) : null}
      </div>
    </button>
  );
}

/**
 * Single clean list container grouped directly by urgency: URGENT first, then OPEN.
 * No per-row buttons; clicking any row opens the full message/detail view.
 */
export function CategoryActionList({ bucket, isLoading = false, onSelectItem }: CategoryActionListProps) {
  const [showAll, setShowAll] = useState(false);

  if (isLoading && bucket.openCount === 0) {
    return (
      <div className="border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] divide-y divide-[var(--line)] overflow-hidden">
        {[1, 2, 3, 4].map((n) => (
          <div key={n} className="px-4 sm:px-5 py-3.5 animate-pulse flex items-center justify-between gap-4">
            <div className="space-y-2 flex-1">
              <div className="h-3.5 w-48 bg-[var(--selected)] rounded" />
              <div className="h-3 w-3/4 bg-[var(--bg)] rounded" />
            </div>
            <div className="h-3 w-12 bg-[var(--selected)] rounded" />
          </div>
        ))}
      </div>
    );
  }

  if (bucket.openCount === 0) {
    return (
      <div className="border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] px-6 py-10 text-center space-y-2">
        <p className="text-[14px] font-medium text-[var(--ink)]">
          All clear in {bucket.meta.label}.
        </p>
        <p className="text-[12.5px] text-[var(--ink-3)]">
          No urgent issues or messages need your call in this category right now.
        </p>
        <div className="pt-1">
          <Link
            href="/inbox"
            className="text-[12.5px] font-medium text-[var(--accent-ink)] hover:underline underline-offset-4"
          >
            Open full Inbox →
          </Link>
        </div>
      </div>
    );
  }

  const urgentVisible = showAll ? bucket.urgentItems : bucket.urgentItems.slice(0, DEFAULT_VISIBLE);
  const remainingSlots = showAll ? bucket.openItems.length : Math.max(0, DEFAULT_VISIBLE - urgentVisible.length);
  const openVisible = bucket.openItems.slice(0, remainingSlots);
  const hiddenCount = Math.max(0, bucket.openCount - urgentVisible.length - openVisible.length);

  return (
    <section
      aria-label={`${bucket.meta.label} actions`}
      className="border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] overflow-hidden divide-y divide-[var(--line)]"
    >
      {urgentVisible.length > 0 && (
        <>
          <div className="px-3.5 sm:px-5 py-1.5 bg-[var(--bg)]/70 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[#B93C00]">
              Urgent ({bucket.urgentCount})
            </span>
          </div>
          {urgentVisible.map((item) => (
            <DashboardListRow key={item.id} item={item} onSelect={onSelectItem} />
          ))}
        </>
      )}

      {openVisible.length > 0 && (
        <>
          <div className="px-3.5 sm:px-5 py-1.5 bg-[var(--bg)]/70 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
              Open ({bucket.openItems.length})
            </span>
          </div>
          {openVisible.map((item) => (
            <DashboardListRow key={item.id} item={item} onSelect={onSelectItem} />
          ))}
        </>
      )}

      {(hiddenCount > 0 || (showAll && bucket.openCount > DEFAULT_VISIBLE)) && (
        <div className="px-4 sm:px-5 py-2.5 bg-[var(--bg)]/50 flex items-center justify-between text-xs">
          <button
            type="button"
            onClick={() => setShowAll((prev) => !prev)}
            className="font-semibold text-[var(--ink)] hover:underline cursor-pointer"
          >
            {showAll ? "Show fewer" : `Show ${hiddenCount} more`}
          </button>
          <Link
            href="/inbox"
            className="font-medium text-[var(--accent-ink)] hover:underline underline-offset-4"
          >
            Open Inbox →
          </Link>
        </div>
      )}
    </section>
  );
}
