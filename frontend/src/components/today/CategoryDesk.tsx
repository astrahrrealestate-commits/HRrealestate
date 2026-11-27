"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Clock, Inbox, Loader2, UserCheck } from "lucide-react";
import {
  chaseFollowup,
  getCategoryDesk,
  getDashboardCategories,
  resolveFollowup,
  type CategoryDeskData,
  type CategoryNextAction,
  type CategorySummaryItem,
} from "@/lib/api";
import {
  categoryLabel,
  fallbackCategorySummaries,
  type BusinessCategory,
  type DashboardTab,
  type UrgencyFilter,
} from "@/lib/categories";
import { CategoryTabs } from "@/components/today/CategoryTabs";
import { ThreadRow, type ThreadRowItem } from "@/components/ui/ThreadRow";
import { cn } from "@/lib/utils";
import { useCachedState } from "@/hooks/useCachedState";
import { readView, writeView } from "@/lib/viewCache";

function actionToThreadRow(action: CategoryNextAction): ThreadRowItem {
  const isDraftReady = Boolean(action.has_draft || action.kind === "approve_draft" || action.approval_id !== null);
  const contactName = action.sender_name || action.title;
  const subjectText = action.sender_name
    ? action.subject || (action.title !== action.sender_name ? action.title : action.why)
    : action.why;
  const snippetText =
    action.obligation ||
    action.prepared ||
    (action.sender_name && action.why !== subjectText ? action.why : "");

  return {
    id: action.id,
    contactName,
    channel: action.channel ?? undefined,
    unit: action.unit_label || "",
    subject: subjectText || action.title,
    snippet: snippetText,
    hasDraft: isDraftReady,
    lastFromUs: action.waiting_side === "third_party",
    lastAt: action.last_at || action.due_at || "",
    urgent: action.urgency === "high",
    urgency: action.urgency,
    waitingDays: action.waiting_days ?? undefined,
    overdueDays: action.overdue_days ?? 0,
    chaseCount: action.chase_count ?? 0,
    waitStatus: action.wait_status ?? undefined,
    dueAt: action.due_at,
    isRead: false,
    category: action.category,
    status: action.waiting_side === "third_party" ? "waiting" : "needs_you",
  };
}

interface CategoryDeskViewProps {
  summaries: readonly CategorySummaryItem[];
  activeCategory: DashboardTab;
  desk: CategoryDeskData | null;
  loading?: boolean;
  offline?: boolean;
  urgencyFilter?: UrgencyFilter;
  onSelectUrgency?: (filter: UrgencyFilter) => void;
  onSelectCategory: (category: DashboardTab) => void;
  onOpenAction?: (action: CategoryNextAction) => void;
  onAskAstra?: (action: CategoryNextAction) => void;
  onChaseFollowup?: (action: CategoryNextAction) => void;
  onResolveFollowup?: (action: CategoryNextAction) => void;
  allContent?: React.ReactNode;
  allCount?: number | null;
  allHasUrgent?: boolean;
}

export function CategoryDeskView({
  summaries,
  activeCategory,
  desk,
  loading = false,
  offline = false,
  urgencyFilter = "all",
  onSelectUrgency,
  onSelectCategory,
  onOpenAction,
  onAskAstra,
  onChaseFollowup,
  onResolveFollowup,
  allContent,
  allCount = null,
  allHasUrgent = false,
}: CategoryDeskViewProps) {
  const showAllTab = Boolean(allContent);
  const isAllTab = activeCategory === "all";
  const label = isAllTab ? "All · BRIXX & Calendar" : (categoryLabel(activeCategory) ?? activeCategory);

  const allActions = useMemo(() => desk?.actions ?? [], [desk?.actions]);
  const emergencyCount = useMemo(
    () => allActions.filter((a) => a.urgency === "emergency").length,
    [allActions]
  );
  const urgentCount = useMemo(
    () => allActions.filter((a) => a.urgency === "high").length,
    [allActions]
  );
  const filteredActions = useMemo(() => {
    if (urgencyFilter === "emergency") return allActions.filter((a) => a.urgency === "emergency");
    if (urgencyFilter === "high") return allActions.filter((a) => a.urgency === "high");
    return allActions;
  }, [allActions, urgencyFilter]);

  const waitingForUs = desk?.waiting_for_us ?? [];
  const waitingForOther = desk?.waiting_for_other ?? [];

  return (
    <section
      aria-label="Category desk"
      className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 sm:p-5 space-y-4"
    >
      <CategoryTabs
        summaries={summaries}
        activeCategory={activeCategory}
        onSelect={onSelectCategory}
        showAllTab={showAllTab}
        allCount={allCount}
        allHasUrgent={allHasUrgent}
      />

      {isAllTab && allContent ? (
        <div className="space-y-4 pt-1">
          <p className="text-[13px] text-[var(--ink-2)]">
            <span className="font-semibold text-[var(--ink)]">{label}</span>
            <span> — Direct BRIXX tickets, rent/lease alerts, and Google Calendar visits (no mail or WhatsApp here).</span>
          </p>
          {allContent}
        </div>
      ) : (
        <>
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-0.5">
            <div className="flex items-center gap-2 min-w-0">
              <p className="text-[13px] text-[var(--ink-2)]">
                <span className="font-semibold text-[var(--ink)]">{label}</span>
                {offline ? (
                  <span> — Offline. Connect to load open actions.</span>
                ) : desk?.brief ? (
                  <span> — &ldquo;{desk.brief}&rdquo;</span>
                ) : loading ? (
                  <span> — Loading actions…</span>
                ) : (
                  <span> — Quiet. Nothing waiting right now.</span>
                )}
              </p>
              {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--ink-3)] shrink-0" />}
            </div>

            {onSelectUrgency && !offline && (
              <div
                role="group"
                aria-label="Urgency filter"
                className="inline-flex items-center rounded-lg border border-[var(--line)] p-0.5 bg-[var(--bg)] text-[11.5px] font-medium shrink-0 self-start sm:self-auto"
              >
                {(
                  [
                    { id: "all", text: "All", count: allActions.length },
                    { id: "emergency", text: "Emergency", count: emergencyCount },
                    { id: "high", text: "Urgent", count: urgentCount },
                  ] as const
                ).map((opt) => {
                  const selected = urgencyFilter === opt.id;
                  return (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => onSelectUrgency(opt.id)}
                      className={cn(
                        "inline-flex items-center gap-1 px-2.5 py-1 rounded-md transition-colors cursor-pointer whitespace-nowrap",
                        selected
                          ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                          : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                      )}
                    >
                      <span>{opt.text}</span>
                      {opt.count > 0 && (
                        <span
                          className={cn(
                            "tabular-nums text-[10.5px]",
                            selected
                              ? "text-white/85"
                              : opt.id === "emergency"
                                ? "text-[#E14D12] font-semibold"
                                : "text-[var(--ink-3)]"
                          )}
                        >
                          {opt.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {!offline && filteredActions.length > 0 ? (
            <div className="rounded-[var(--radius-pane)] border border-[var(--line)] overflow-hidden bg-[var(--pane)]">
              {filteredActions.map((action) => {
                const isDraftReady = Boolean(
                  action.has_draft || action.kind === "approve_draft" || action.approval_id !== null
                );
                return (
                  <div key={action.id}>
                    <ThreadRow
                      t={actionToThreadRow(action)}
                      actionLabel={isDraftReady ? "Review draft" : "Open"}
                      onSelect={() => onOpenAction?.(action)}
                      onAskAstra={onAskAstra ? () => onAskAstra(action) : undefined}
                    />
                    <div className="sr-only">
                      <span>{action.title}</span>
                      <span>{action.why}</span>
                      {action.prepared && <span>{action.prepared}</span>}
                      <Link href={action.target_url || "/inbox"}>
                        {isDraftReady ? "Review draft" : "Open"}
                      </Link>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : !offline && !loading ? (
            <div className="rounded-lg border border-dashed border-[var(--line)] bg-[var(--bg)]/50 px-4 py-5 text-center text-[12.5px] text-[var(--ink-3)]">
              {urgencyFilter === "all"
                ? `No open ${label.toLowerCase()} messages needing action right now.`
                : `No ${urgencyFilter === "emergency" ? "emergency" : "urgent"} items in ${label}.`}
            </div>
          ) : null}

          {!offline && (waitingForUs.length > 0 || waitingForOther.length > 0) && (
            <div className="pt-2 border-t border-[var(--line)] space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-[12px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                  Commitments &amp; Chasing Radar · {label}
                </h3>
                <span className="text-[11px] text-[var(--ink-3)] tabular-nums">
                  {waitingForUs.length + waitingForOther.length} tracked
                </span>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* Subsection 1: Owed by Us */}
                <div className="rounded-[var(--radius-pane)] border border-[var(--line)] bg-[var(--bg)]/40 overflow-hidden">
                  <div className="px-3.5 py-2.5 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <Inbox className="w-3.5 h-3.5 text-[var(--accent-ink)] shrink-0" />
                      <span className="text-[12.5px] font-semibold text-[var(--ink)] truncate">
                        Owed by Us
                      </span>
                    </div>
                    <span className="text-[11px] font-semibold tabular-nums text-[var(--ink-2)]">
                      {waitingForUs.length}
                    </span>
                  </div>
                  {waitingForUs.length > 0 ? (
                    <div className="divide-y divide-[var(--line)]">
                      {waitingForUs.map((item) => {
                        const isDraftReady = Boolean(item.has_draft || item.approval_id !== null);
                        return (
                          <ThreadRow
                            key={item.id}
                            t={actionToThreadRow(item)}
                            actionLabel={isDraftReady ? "Review draft" : undefined}
                            onSelect={() => onOpenAction?.(item)}
                            onDone={onResolveFollowup ? () => onResolveFollowup(item) : undefined}
                            onAskAstra={onAskAstra ? () => onAskAstra(item) : undefined}
                          />
                        );
                      })}
                    </div>
                  ) : (
                    <p className="px-3.5 py-4 text-[12px] text-[var(--ink-3)]">
                      No overdue replies or open promises owed by us.
                    </p>
                  )}
                </div>

                {/* Subsection 2: Owed by Others */}
                <div className="rounded-[var(--radius-pane)] border border-[var(--line)] bg-[var(--bg)]/40 overflow-hidden">
                  <div className="px-3.5 py-2.5 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      {waitingForOther.length > 0 ? (
                        <Clock className="w-3.5 h-3.5 text-[var(--ink-2)] shrink-0" />
                      ) : (
                        <UserCheck className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" />
                      )}
                      <span className="text-[12.5px] font-semibold text-[var(--ink)] truncate">
                        Owed by Others
                      </span>
                    </div>
                    <span className="text-[11px] font-semibold tabular-nums text-[var(--ink-2)]">
                      {waitingForOther.length}
                    </span>
                  </div>
                  {waitingForOther.length > 0 ? (
                    <div className="divide-y divide-[var(--line)]">
                      {waitingForOther.map((item) => {
                        const hasDraft = Boolean(item.has_draft || item.approval_id !== null);
                        const canChase =
                          !hasDraft && ((item.overdue_days ?? 0) > 0 || item.wait_status === "escalated");
                        return (
                          <ThreadRow
                            key={item.id}
                            t={actionToThreadRow(item)}
                            actionLabel={hasDraft ? "Review chaser" : undefined}
                            onSelect={() => onOpenAction?.(item)}
                            onChase={canChase && onChaseFollowup ? () => onChaseFollowup(item) : undefined}
                            onDone={onResolveFollowup ? () => onResolveFollowup(item) : undefined}
                            onAskAstra={onAskAstra ? () => onAskAstra(item) : undefined}
                          />
                        );
                      })}
                    </div>
                  ) : (
                    <p className="px-3.5 py-4 text-[12px] text-[var(--ink-3)]">
                      Nothing overdue or awaited from third parties in {label}.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

interface CategoryDeskProps {
  onAskAstra?: (action: CategoryNextAction) => void;
  allContent?: React.ReactNode;
  allCount?: number | null;
  allHasUrgent?: boolean;
}

export function CategoryDesk({
  onAskAstra,
  allContent,
  allCount = null,
  allHasUrgent = false,
}: CategoryDeskProps) {
  const router = useRouter();
  const [summaries, setSummaries] = useCachedState<CategorySummaryItem[]>("today.categories", fallbackCategorySummaries());
  const [activeCategory, setActiveCategory] = useCachedState<DashboardTab>("today.category", "finance");
  const [urgencyFilter, setUrgencyFilter] = useState<UrgencyFilter>("all");
  const [desk, setDesk] = useState<CategoryDeskData | null>(() => readView(`today.desk.${activeCategory}`) ?? null);
  const [loading, setLoading] = useState<boolean>(desk === null);
  const [offline, setOffline] = useState<boolean>(false);

  useEffect(() => {
    let active = true;
    getDashboardCategories().then((loaded) => {
      if (!active) return;
      if (!loaded) {
        setOffline(true);
        setLoading(false);
        return;
      }
      setOffline(false);
      setSummaries(loaded);
    });
    return () => {
      active = false;
    };
  }, [setSummaries]);

  useEffect(() => {
    if (offline || activeCategory === "all") {
      return;
    }
    let active = true;
    getCategoryDesk(activeCategory as BusinessCategory).then((data) => {
      if (!active) return;
      if (!data) {
        setOffline(true);
      } else {
        writeView(`today.desk.${activeCategory}`, data);
        setDesk(data);
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [activeCategory, offline]);

  const handleSelect = (category: DashboardTab) => {
    setUrgencyFilter("all");
    const seen = readView<CategoryDeskData>(`today.desk.${category}`);
    if (seen) setDesk(seen);
    setLoading(category !== "all" && !seen);
    setActiveCategory(category);
  };

  const refreshDesk = async () => {
    if (activeCategory === "all") return;
    const data = await getCategoryDesk(activeCategory as BusinessCategory);
    if (data) {
      writeView(`today.desk.${activeCategory}`, data);
      setDesk(data);
    }
  };

  const handleChaseFollowup = async (action: CategoryNextAction) => {
    if (!action.case_id) return;
    const res = await chaseFollowup(action.case_id);
    if (res?.approval_id) {
      await refreshDesk();
      router.push(action.target_url || "/inbox");
    }
  };

  const handleResolveFollowup = async (action: CategoryNextAction) => {
    if (!action.case_id) return;
    setDesk((prev) =>
      prev
        ? {
            ...prev,
            waiting_for_us: (prev.waiting_for_us ?? []).filter((x) => x.id !== action.id),
            waiting_for_other: (prev.waiting_for_other ?? []).filter((x) => x.id !== action.id),
          }
        : prev
    );
    const ok = await resolveFollowup(action.case_id);
    if (ok) {
      await refreshDesk();
    }
  };

  return (
    <CategoryDeskView
      summaries={summaries}
      activeCategory={activeCategory}
      desk={desk}
      loading={loading}
      offline={offline}
      urgencyFilter={urgencyFilter}
      onSelectUrgency={setUrgencyFilter}
      onSelectCategory={handleSelect}
      onOpenAction={(action) => router.push(action.target_url || "/inbox")}
      onAskAstra={onAskAstra}
      onChaseFollowup={handleChaseFollowup}
      onResolveFollowup={handleResolveFollowup}
      allContent={allContent}
      allCount={allCount}
      allHasUrgent={allHasUrgent}
    />
  );
}
