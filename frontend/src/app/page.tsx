"use client";

import React, { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, ChevronDown, Sparkles } from "lucide-react";
import { WorkspaceShell } from "@/components/layout/WorkspaceShell";
import { StatLine, StatItem } from "@/components/ui/StatLine";
import { CategoryPills } from "@/components/today/CategoryPills";
import { CategoryActionList } from "@/components/today/CategoryActionList";
import { CalendarApprovalsCard } from "@/components/today/CalendarApprovalsCard";
import { BrixxAttentionCard } from "@/components/today/BrixxAttentionCard";
import { StalledItem } from "@/components/today/UnresponsiveRadarCard";
import { formatLongDay } from "@/lib/clock";
import { cn, formatCurrency } from "@/lib/utils";
import {
  buildAllBucket,
  buildCategoryBrief,
  buildCategoryBuckets,
  DashboardItem,
  DashboardTabId,
} from "@/lib/dashboardCategories";
import { needsYouCount, urgentCount } from "@/lib/selectors";
import {
  CalendarEvent,
  getCalendarEvents,
  getDashboardAttention,
  getDashboardBriefing,
  getDashboardInquiries,
  getDashboardPulse,
  getDashboardRadar,
  getInboxThreads,
  getMaintenanceTickets,
  MaintenanceTicket,
  ProspectiveInquiry,
  syncGmailInbox,
  type AttentionItem,
} from "@/lib/api";
import { getPortfolio, getTenantProfiles } from "@/lib/portfolioApi";
import type { PropertyComplex, TenantProfile } from "@/types/portfolio";
import { InboxThread } from "@/types/inbox";
import { PulseMetrics } from "@/types/dashboard";
import { INITIAL_METRICS } from "@/data/mockData";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";

function greetingPrefix(): string {
  if (typeof window === "undefined") return "Good morning";
  const hr = new Date().getHours();
  if (hr < 12) return "Good morning";
  if (hr < 18) return "Good afternoon";
  return "Good evening";
}

interface BriefingPayload {
  headline: string;
  summarySentence: string;
  sections: Array<{ category: string; headline: string; details: string; urgency: string }>;
}

export default function TodayPage() {
  const router = useRouter();
  const { user, canAccess } = useAuth();
  const { t } = useLanguage();

  // Live backend state
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [attentionTotal, setAttentionTotal] = useState<number>(0);
  const [maintenanceTickets, setMaintenanceTickets] = useState<MaintenanceTicket[]>([]);
  const [radarItems, setRadarItems] = useState<StalledItem[]>([]);
  const [inquiries, setInquiries] = useState<ProspectiveInquiry[]>([]);
  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [metrics, setMetrics] = useState<PulseMetrics>(INITIAL_METRICS);
  const [portfolio, setPortfolio] = useState<PropertyComplex[] | null>(null);
  const [tenants, setTenants] = useState<TenantProfile[] | null>(null);
  const [briefingKind, setBriefingKind] = useState<"daily" | "weekly">("daily");
  const [briefingData, setBriefingData] = useState<BriefingPayload | null>(null);
  const [isBriefingExpanded, setIsBriefingExpanded] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);

  // Active tab ("all" shows unified overview + meeting requests + BRIXX; 6 categories filter by area)
  const [activeTab, setActiveTab] = useState<DashboardTabId>("all");
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [clientClock, setClientClock] = useState<{ day: string; greeting: string } | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3200);
  }, []);

  useEffect(() => {
    const id = requestAnimationFrame(() => {
      setClientClock({
        day: formatLongDay(new Date()),
        greeting: greetingPrefix(),
      });
    });
    return () => cancelAnimationFrame(id);
  }, []);

  const fetchDashboardSnapshot = useCallback(async () => {
    const [threadsRes, pulseRes, attentionRes, ticketsRes, calRes] = await Promise.allSettled([
      getInboxThreads({ limit: 100, sort: "priority", includeHtml: false }),
      getDashboardPulse(),
      getDashboardAttention(),
      getMaintenanceTickets(),
      getCalendarEvents({ status: "proposed" }),
    ]);

    return { threadsRes, pulseRes, attentionRes, ticketsRes, calRes };
  }, []);

  const commitDashboardSnapshot = useCallback(
    (snap: Awaited<ReturnType<typeof fetchDashboardSnapshot>>) => {
      if (snap.threadsRes.status === "fulfilled") {
        setThreads(snap.threadsRes.value.threads || []);
      }
      if (snap.pulseRes.status === "fulfilled" && snap.pulseRes.value.isLive) {
        setMetrics(snap.pulseRes.value.metrics);
      }
      if (snap.attentionRes.status === "fulfilled") {
        setAttentionItems(snap.attentionRes.value.items || []);
        setAttentionTotal(snap.attentionRes.value.total || 0);
      }
      if (snap.ticketsRes.status === "fulfilled" && snap.ticketsRes.value.isLive) {
        setMaintenanceTickets(snap.ticketsRes.value.tickets || []);
      }
      if (snap.calRes.status === "fulfilled" && snap.calRes.value.isLive) {
        setCalendarEvents(snap.calRes.value.events || []);
      }
    },
    []
  );

  useEffect(() => {
    let mounted = true;
    fetchDashboardSnapshot()
      .then((snap) => {
        if (mounted) commitDashboardSnapshot(snap);
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });

    const secondaryTimer = setTimeout(() => {
      if (!mounted) return;
      Promise.allSettled([
        getPortfolio(),
        getTenantProfiles(),
        getDashboardRadar(),
        getDashboardInquiries(),
      ]).then(([pRes, tRes, rRes, iRes]) => {
        if (!mounted) return;
        if (pRes.status === "fulfilled" && pRes.value.ok) setPortfolio(pRes.value.data);
        if (tRes.status === "fulfilled" && tRes.value.ok) setTenants(tRes.value.data);
        if (rRes.status === "fulfilled" && rRes.value.isLive) setRadarItems(rRes.value.items || []);
        if (iRes.status === "fulfilled" && iRes.value.isLive) setInquiries(iRes.value.inquiries || []);
      });
    }, 160);

    return () => {
      mounted = false;
      clearTimeout(secondaryTimer);
    };
  }, [fetchDashboardSnapshot, commitDashboardSnapshot]);

  useEffect(() => {
    let mounted = true;
    getDashboardBriefing(briefingKind)
      .then(({ data, isLive }) => {
        if (mounted && isLive && data) {
          setBriefingData(data);
        }
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, [briefingKind]);

  // Build 6 category buckets sorted by urgency + unified "All" bucket (threads/radar/leads; BRIXX & Calendar have dedicated cards on All)
  const buckets = useMemo(
    () =>
      buildCategoryBuckets({
        threads,
        attentionItems,
        maintenanceTickets,
        radarItems,
        inquiries,
        calendarEvents,
      }),
    [threads, attentionItems, maintenanceTickets, radarItems, inquiries, calendarEvents]
  );

  const allBucket = useMemo(
    () => buildAllBucket(buckets, { includeBrixx: false, includeCalendar: false }),
    [buckets]
  );

  const activeBucket = activeTab === "all" ? allBucket : buckets[activeTab];

  // Single source of truth counts
  const currentNeedsYouCount = useMemo(() => needsYouCount(threads), [threads]);
  const urgentAttentionCount = useMemo(
    () => attentionItems.filter((i) => i.urgent && i.kind !== "rent").length,
    [attentionItems]
  );
  const currentUrgentCount = useMemo(
    () => urgentCount(threads) + urgentAttentionCount,
    [threads, urgentAttentionCount]
  );

  // Portfolio footer stats
  const overdueTenants = useMemo(
    () => (tenants ?? []).filter((t) => t.rentStatus === "overdue" && t.overdueDays > 0 && (t.monthlyRentEur ?? 0) > 0),
    [tenants]
  );
  const agingTotal = useMemo(
    () => overdueTenants.reduce((sum, t) => sum + (t.monthlyRentEur ?? 0), 0),
    [overdueTenants]
  );
  const portfolioUnits = useMemo(
    () => (portfolio ?? []).reduce((sum, c) => sum + c.totalUnits, 0),
    [portfolio]
  );
  const portfolioOccupied = useMemo(
    () => (portfolio ?? []).reduce((sum, c) => sum + c.occupiedUnits, 0),
    [portfolio]
  );
  const occupancyHeadline =
    portfolio && portfolioUnits > 0
      ? `${Math.round((portfolioOccupied / portfolioUnits) * 1000) / 10}%`
      : metrics.totalUnits > 0
        ? `${metrics.occupancyPercentage}%`
        : "—";

  const statLineItems: StatItem[] = useMemo(
    () => [
      {
        count: currentNeedsYouCount,
        label: t("need you"),
        href: "/inbox",
      },
      {
        count: currentUrgentCount,
        label: t("urgent"),
        urgent: currentUrgentCount > 0,
        href: "/inbox",
      },
      {
        count: metrics.autonomousActionsWeek,
        label: t("handled this week"),
      },
    ],
    [currentNeedsYouCount, currentUrgentCount, metrics.autonomousActionsWeek, t]
  );

  const handleSyncMailbox = async () => {
    setIsSyncing(true);
    try {
      const res = await syncGmailInbox();
      showToast(res.message);
      const snap = await fetchDashboardSnapshot();
      commitDashboardSnapshot(snap);
    } catch {
      showToast("Sync finished.");
    } finally {
      setIsSyncing(false);
    }
  };

  // Direct navigation on click (no side drawer)
  const handleSelectItem = (item: DashboardItem) => {
    if (item.thread) {
      router.push(`/inbox?thread=${encodeURIComponent(item.thread.id)}`);
      return;
    }
    if (item.href) {
      router.push(item.href);
      return;
    }
    if (item.kind === "radar" && item.radarItem) {
      router.push("/inbox");
      return;
    }
    if (item.kind === "calendar") {
      setActiveTab("all");
      return;
    }
  };

  const firstName = user?.name?.trim().split(/\s+/)[0] ?? "";

  return (
    <WorkspaceShell
      pageTitle="Main Dashboard"
      pendingCount={currentNeedsYouCount}
      threads={threads}
      onSyncMailbox={handleSyncMailbox}
      isSyncing={isSyncing}
      agentPageName="Today"
      agentContext={`${activeTab === "all" ? "All" : activeBucket.meta.label} · ${currentNeedsYouCount} need you · ${currentUrgentCount} urgent`}
      onAgentAction={(actionType) => {
        if (actionType === "approve_queue_item") {
          router.push("/inbox");
        } else {
          showToast(`Action triggered: ${actionType}`);
        }
      }}
    >
      <main className="flex-1 w-full max-w-[920px] mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-8 pb-24 md:pb-12 space-y-5 overflow-y-auto">
        {/* Top Greeting & Live Executive Briefing */}
        <header className="space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
            <div>
              <p className="text-[12px] sm:text-[13px] font-medium text-[var(--ink-3)] tracking-tight">
                {clientClock?.day ? `${clientClock.day} · Amsterdam (CET)` : "Amsterdam (CET)"}
              </p>
              <h1 className="font-heading font-bold text-[24px] sm:text-[30px] text-[var(--ink)] tracking-tight leading-tight mt-0.5">
                {briefingKind === "daily" ? clientClock?.greeting ?? "Good morning" : "Weekly executive review"}
                {firstName ? `, ${firstName}` : ""}
              </h1>
            </div>

            <div className="inline-flex rounded-lg border border-[var(--line)] p-0.5 bg-[var(--pane)] text-xs font-medium shrink-0 self-start sm:self-auto">
              <button
                type="button"
                onClick={() => setBriefingKind("daily")}
                className={cn(
                  "px-2.5 py-1 rounded-md transition-colors cursor-pointer",
                  briefingKind === "daily"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                )}
              >
                Daily pulse
              </button>
              <button
                type="button"
                onClick={() => setBriefingKind("weekly")}
                className={cn(
                  "px-2.5 py-1 rounded-md transition-colors cursor-pointer",
                  briefingKind === "weekly"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                )}
              >
                Weekly recap
              </button>
            </div>
          </div>

          {/* Live AI Briefing Sentence */}
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2.5">
            <p className="text-[13.5px] sm:text-[14.5px] text-[var(--ink-2)] leading-relaxed">
              <Sparkles className="w-3.5 h-3.5 text-[var(--accent)] inline-block mr-1.5 -mt-0.5" />
              {briefingData?.summarySentence ? (
                <span>{briefingData.summarySentence} </span>
              ) : (
                <span>{buildCategoryBrief(activeBucket)} </span>
              )}
              <Link
                href="/inbox"
                className="font-semibold text-[var(--ink)] hover:underline underline-offset-4 whitespace-nowrap"
              >
                {currentNeedsYouCount} need your call
              </Link>
              {currentUrgentCount > 0 ? (
                <>
                  ,{" "}
                  <Link
                    href="/inbox"
                    className="font-semibold text-[var(--accent-ink)] hover:underline underline-offset-4 whitespace-nowrap"
                  >
                    {currentUrgentCount} {currentUrgentCount === 1 ? "is" : "are"} urgent
                  </Link>
                </>
              ) : null}
              .
            </p>

            {briefingData?.sections && briefingData.sections.length > 0 && (
              <button
                type="button"
                onClick={() => setIsBriefingExpanded((prev) => !prev)}
                className="text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] inline-flex items-center gap-1 cursor-pointer shrink-0 self-start py-1 px-2 rounded-md border border-[var(--line)] hover:bg-[var(--selected)]"
              >
                <span>{isBriefingExpanded ? "Hide breakdown" : "Breakdown"}</span>
                <ChevronDown
                  className={cn("w-3.5 h-3.5 transition-transform duration-150", isBriefingExpanded && "rotate-180")}
                />
              </button>
            )}
          </div>

          {isBriefingExpanded && briefingData?.sections && (
            <div className="p-3.5 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] grid grid-cols-1 md:grid-cols-3 gap-2.5">
              {briefingData.sections.map((sec, idx) => (
                <div
                  key={idx}
                  className={cn(
                    "p-3 rounded-lg border text-xs space-y-1",
                    sec.urgency === "emergency"
                      ? "bg-[#E14D12]/5 border-[#E14D12]/25"
                      : "bg-[var(--bg)] border-[var(--line)]"
                  )}
                >
                  <span className="font-semibold uppercase tracking-wider text-[10.5px] text-[var(--ink-3)]">
                    {sec.category}
                  </span>
                  <div className="font-semibold text-[13px] text-[var(--ink)] leading-snug">{sec.headline}</div>
                  <div className="text-[12px] text-[var(--ink-2)] leading-relaxed">{sec.details}</div>
                </div>
              ))}
            </div>
          )}

          <StatLine items={statLineItems} className="pt-0.5" />
        </header>

        {/* All + 6 Main Categories */}
        <CategoryPills
          activeTab={activeTab}
          allCount={allBucket.openCount}
          allUrgentCount={allBucket.urgentCount}
          buckets={buckets}
          onSelect={(tab) => setActiveTab(tab)}
        />

        {/* Mails & Actions Sorted by Urgency (click any row to open exact thread in /inbox) */}
        <CategoryActionList
          bucket={activeBucket}
          isLoading={isLoading}
          onSelectItem={handleSelectItem}
        />

        {/* Meeting Requests & BRIXX Attention on the All Overview */}
        {activeTab === "all" && (
          <div className="space-y-5">
            <CalendarApprovalsCard
              onApproveSuccess={(_eventId, title) => {
                showToast(`Visit approved & synced to Google Calendar: ${title}`);
              }}
              onInviteAnswered={(title, response) => {
                showToast(`Invite ${response}: ${title}`);
              }}
            />

            <BrixxAttentionCard
              items={attentionItems}
              total={attentionTotal}
              urgentTotal={urgentAttentionCount}
              onlyUrgent={false}
            />
          </div>
        )}

        {/* Quiet Single-Line Portfolio Footer */}
        <footer className="border-t border-[var(--line)] pt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-[12px] text-[var(--ink-3)]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {canAccess("money") && (
              <Link href="/money" className="hover:text-[var(--ink)] transition-colors">
                Open rent{" "}
                <span className="font-mono font-medium text-[var(--ink-2)] tabular-nums">
                  {agingTotal > 0 ? formatCurrency(agingTotal) : "—"}
                </span>
              </Link>
            )}
            {canAccess("money") && canAccess("properties") && <span className="text-[var(--line)]">|</span>}
            {canAccess("properties") && (
              <Link href="/properties" className="hover:text-[var(--ink)] transition-colors">
                Occupancy{" "}
                <span className="font-mono font-medium text-[var(--ink-2)] tabular-nums">
                  {occupancyHeadline}
                </span>
                {portfolioUnits > 0 ? (
                  <span className="ml-1">
                    ({portfolioOccupied}/{portfolioUnits} units)
                  </span>
                ) : null}
              </Link>
            )}
          </div>

          <Link
            href="/inbox"
            className="inline-flex items-center gap-1 font-medium text-[var(--ink-2)] hover:text-[var(--ink)] whitespace-nowrap"
          >
            <span>Open full Inbox</span>
            <ArrowRight className="w-3 h-3" />
          </Link>
        </footer>
      </main>

      {toastMessage && (
        <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] left-3.5 right-3.5 md:left-auto md:bottom-6 md:right-6 z-50 bg-[#0A0A0A] text-white text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[var(--accent)] shrink-0" />
          <span>{toastMessage}</span>
        </div>
      )}
    </WorkspaceShell>
  );
}
