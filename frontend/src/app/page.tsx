"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { format } from "date-fns";
import { ArrowRight, Check, Send, AlertTriangle, ShieldCheck, ChevronDown } from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { ThreadRow, ThreadRowItem } from "@/components/ui/ThreadRow";
import { StatLine, StatItem } from "@/components/ui/StatLine";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Button } from "@/components/ui/Button";
import { formatCurrency, cn } from "@/lib/utils";
import {
  getInboxThreads,
  getDashboardPulse,
  getDashboardRadar,
  getDashboardInquiries,
  getAutonomousLogs,
  getDashboardBriefing,
  syncGmailInbox,
  ProspectiveInquiry,
} from "@/lib/api";
import { StalledItem, INITIAL_STALLED_ITEMS } from "@/components/today/UnresponsiveRadarCard";
import { InboxThread } from "@/types/inbox";
import { PulseMetrics, AutonomousActionLog } from "@/types/dashboard";
import { INITIAL_METRICS, RECENT_AUTONOMOUS_LOGS } from "@/data/mockData";
import { MOCK_INBOX_THREADS } from "@/data/inboxMockData";
import {
  needsYou,
  needsYouCount,
  urgent,
  urgentCount,
  isNeedsYou,
  isUrgent,
} from "@/lib/selectors";
import { useSuperAgent } from "@/context/SuperAgentContext";

export default function TodayPage() {
  const router = useRouter();
  const superAgent = useSuperAgent();

  // State
  const [threads, setThreads] = useState<InboxThread[]>(MOCK_INBOX_THREADS);
  const [metrics, setMetrics] = useState<PulseMetrics>(INITIAL_METRICS);
  const [radarItems, setRadarItems] = useState<StalledItem[]>(INITIAL_STALLED_ITEMS);
  const [inquiries, setInquiries] = useState<ProspectiveInquiry[]>([]);
  const [logs, setLogs] = useState<AutonomousActionLog[]>(RECENT_AUTONOMOUS_LOGS);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);
  const [isEmergencyExpanded, setIsEmergencyExpanded] = useState<boolean>(false);
  const [nudgedItemIds, setNudgedItemIds] = useState<Record<string, boolean>>({});

  // Fetch live threads and dashboard data
  useEffect(() => {
    let isMounted = true;

    // 1. Inbox threads (Single source of truth for Needs You and Urgent counts)
    getInboxThreads()
      .then(({ threads: live }) => {
        if (isMounted && live && live.length > 0) {
          setThreads(live);
        }
      })
      .catch((err) => console.warn("Failed to load threads on Today:", err));

    // 2. Metrics & radar & inquiries & logs
    Promise.all([
      getDashboardPulse(),
      getDashboardRadar(),
      getDashboardInquiries(),
      getAutonomousLogs(),
    ])
      .then(([pRes, rRes, iRes, lRes]) => {
        if (!isMounted) return;
        if (pRes.isLive) setMetrics(pRes.metrics);
        if (rRes.isLive && rRes.items.length > 0) setRadarItems(rRes.items);
        if (iRes.isLive && iRes.inquiries.length > 0) setInquiries(iRes.inquiries);
        if (lRes.isLive && lRes.logs.length > 0) setLogs(lRes.logs);
      })
      .catch((err) => console.warn("Failed to load auxiliary dashboard data:", err));

    return () => {
      isMounted = false;
    };
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const handleSendNudge = (item: StalledItem) => {
    setNudgedItemIds((prev) => ({ ...prev, [item.id]: true }));
    showToast(`Nudge sent to ${item.partyName} (${item.unitLabel}) via ${item.contact.includes("@") ? "Email" : "WhatsApp"}.`);
  };

  // Selectors: Single source of truth (Section 2.5 D1 & 6.4)
  const currentNeedsYouCount = needsYouCount(threads);
  const currentUrgentCount = urgentCount(threads);
  const urgentThreads = urgent(threads);
  const needsYouThreads = needsYou(threads);

  // Top urgent thread for slim emergency bar
  const topUrgentThread = urgentThreads[0] || null;

  useEffect(() => {
    superAgent.setCurrentPageName("Today");
    superAgent.setSelectedContext(
      `Today Briefing [${currentNeedsYouCount} need you, ${currentUrgentCount} urgent, Top item: ${topUrgentThread?.subject || "All clear"}]`
    );
  }, [currentNeedsYouCount, currentUrgentCount, topUrgentThread, superAgent.setCurrentPageName, superAgent.setSelectedContext]);

  // StatLine items (Section 2.3 T6 & 5.3)
  const statLineItems: StatItem[] = useMemo(() => [
    {
      count: currentNeedsYouCount,
      label: "need you",
      href: "/inbox",
    },
    {
      count: currentUrgentCount,
      label: "urgent",
      urgent: currentUrgentCount > 0,
      href: "/inbox",
    },
    {
      count: metrics.autonomousActionsWeek || 142,
      label: "handled this week",
    },
  ], [currentNeedsYouCount, currentUrgentCount, metrics.autonomousActionsWeek]);

  // Today Date & Greeting - Defer evaluation to client mount to prevent Next.js prerender error
  const [todayFormatted, setTodayFormatted] = useState<string>("Thursday 15 October");

  useEffect(() => {
    setTodayFormatted(format(new Date(), "EEEE d MMMM"));
  }, []);

  // Lead rows fallback
  const leadItems: ProspectiveInquiry[] = inquiries.length > 0 ? inquiries.slice(0, 3) : [
    {
      id: "lead-1",
      name: "Sanne Meijer",
      contact: "sanne.meijer@uva.nl",
      channel: "gmail",
      unit: "Pieter Floriszstraat 1 C",
      moveIn: "1 Nov 2026",
      request: "Viewing Thursday 15:00 slot",
      qualification: "3.2x income verified (UvA lecturer)",
      status: "AI draft ready",
    },
    {
      id: "lead-2",
      name: "Lucas van Dijk",
      contact: "+31 6 81 29 44 10",
      channel: "whatsapp",
      unit: "Singel 412 Studio",
      moveIn: "1 Nov 2026",
      request: "Studio availability & viewing inquiry",
      qualification: "Preliminary criteria met",
      status: "AI draft ready",
    },
    {
      id: "lead-3",
      name: "Elena Rostova",
      contact: "elena.rostova@booking.com",
      channel: "gmail",
      unit: "Keizersgracht 42-B",
      moveIn: "15 Nov 2026",
      request: "Viewing & expat registration query",
      qualification: "Booking.com Senior Software Engineer",
      status: "AI draft ready",
    },
  ];

  // Financial Aging distribution for bottom pane
  const agingBuckets = [
    { label: "0–30 days", amount: "€ 120.400,-", pct: 72.6, barClass: "bg-[var(--ink)]" },
    { label: "30–90 days", amount: "€ 35.334,99", pct: 21.3, barClass: "bg-[var(--ink-3)]" },
    { label: "90+ days", amount: "€ 10.000,-", pct: 6.1, barClass: "bg-[var(--accent)]" },
  ];

  // Occupancy distribution per building
  const occupancyBuildings = [
    { name: "Keizersgracht (42-46)", rate: 100, occupied: 42, total: 42 },
    { name: "Prinsengracht (118-124)", rate: 92.1, occupied: 35, total: 38 },
    { name: "Herengracht Historic", rate: 90.0, occupied: 27, total: 30 },
  ];

  // Briefing mode: Daily pulse vs Weekly recap
  const [briefingKind, setBriefingKind] = useState<"daily" | "weekly">("daily");
  const [briefingData, setBriefingData] = useState<{
    headline: string;
    summarySentence: string;
    sections: Array<{ category: string; headline: string; details: string; urgency: string }>;
  } | null>(null);
  const [isBriefingExpanded, setIsBriefingExpanded] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    getDashboardBriefing(briefingKind)
      .then(({ data, isLive }) => {
        if (isMounted && isLive && data) {
          setBriefingData(data);
        }
      })
      .catch((err) => console.warn("Failed to load live briefing:", err));

    return () => {
      isMounted = false;
    };
  }, [briefingKind]);

  return (
    <div className="h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar pendingCount={currentNeedsYouCount} />

      {/* 2. Main Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        <TopCommandBar
          pageTitle="Today"
        />

        {/* Scrollable Single-Column Briefing (Section 5.3) */}
        <main className="flex-1 w-full max-w-[960px] mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8 pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12 space-y-7 overflow-y-auto">
          
          {/* Top Briefing Header with Daily / Weekly Switcher */}
          <div className="space-y-3 select-none">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <span className="text-[13px] font-medium text-[var(--ink-3)] block tracking-tight">
                  {briefingKind === "daily" ? todayFormatted : "WEEK 40 EXECUTIVE RECAP · Friday 16:00 CET"}
                </span>
                <h1 className="font-heading font-bold text-[28px] sm:text-[32px] text-[var(--ink)] tracking-tight leading-none mt-1">
                  {briefingKind === "daily" ? "Good morning, Harjot" : "Weekly executive review, Harjot"}
                </h1>
              </div>

              {/* Daily vs Weekly Switcher */}
              <div className="inline-flex rounded-lg border border-[var(--line)] p-0.5 bg-[var(--pane)] text-xs font-medium shrink-0 self-start sm:self-auto">
                <button
                  type="button"
                  onClick={() => setBriefingKind("daily")}
                  className={cn(
                    "px-3 py-1.5 rounded-md transition-colors cursor-pointer",
                    briefingKind === "daily"
                      ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                      : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                  )}
                >
                  Daily pulse
                </button>
                <button
                  type="button"
                  onClick={() => setBriefingKind("weekly")}
                  className={cn(
                    "px-3 py-1.5 rounded-md transition-colors cursor-pointer",
                    briefingKind === "weekly"
                      ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                      : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                  )}
                >
                  Weekly recap
                </button>
              </div>
            </div>

            {/* Sparkle Briefing Sentence with linked counts */}
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 pt-1">
              <p className="text-[14px] sm:text-[15px] text-[var(--ink-2)] leading-relaxed">
                <span className="text-[var(--accent)] font-bold mr-1.5 select-none">✦</span>
                {briefingData?.summarySentence ? (
                  <span>{briefingData.summarySentence} </span>
                ) : briefingKind === "daily" ? (
                  <>Since yesterday evening I read 22 messages and answered 17. </>
                ) : (
                  <>Portfolio operating at peak efficiency across all 110 units. </>
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
                      {currentUrgentCount} is urgent
                    </Link>
                  </>
                ) : null}
                .
              </p>

              {briefingData?.sections && briefingData.sections.length > 0 && (
                <button
                  type="button"
                  onClick={() => setIsBriefingExpanded((prev) => !prev)}
                  className="text-xs font-semibold text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center gap-1 cursor-pointer shrink-0 self-start py-1 px-2 rounded-md hover:bg-[var(--selected)] transition-colors border border-[var(--line)]"
                >
                  <span>{isBriefingExpanded ? "Hide briefing breakdown" : "View briefing breakdown"}</span>
                  <ChevronDown
                    className={cn(
                      "w-3.5 h-3.5 transition-transform duration-200",
                      isBriefingExpanded && "rotate-180"
                    )}
                  />
                </button>
              )}
            </div>

            {/* Expandable Briefing Breakdown from Backend */}
            {isBriefingExpanded && briefingData?.sections && (
              <div className="mt-3 p-4 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] space-y-3 shadow-2xs animate-in fade-in duration-200">
                <div className="text-xs font-bold uppercase tracking-wider text-[var(--ink-3)]">
                  Live Executive Breakdown · {briefingKind === "daily" ? "Morning Pulse" : "Weekly Recap"}
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {briefingData.sections.map((sec, idx) => (
                    <div
                      key={idx}
                      className={cn(
                        "p-3 rounded-lg border text-xs space-y-1.5",
                        sec.urgency === "emergency"
                          ? "bg-[var(--accent)]/5 border-[var(--accent)]/30 text-[var(--ink)]"
                          : sec.urgency === "high"
                          ? "bg-amber-500/5 border-amber-500/30 text-[var(--ink)]"
                          : "bg-[var(--bg)] border-[var(--line)] text-[var(--ink)]"
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold uppercase tracking-wider text-[11px] text-[var(--ink-3)]">
                          {sec.category}
                        </span>
                        {sec.urgency === "emergency" && (
                          <span className="font-mono text-[10px] font-bold text-[var(--accent-ink)] bg-[var(--accent)]/15 px-1.5 py-0.5 rounded">
                            Action
                          </span>
                        )}
                      </div>
                      <div className="font-semibold text-[13px] text-[var(--ink)] leading-snug">
                        {sec.headline}
                      </div>
                      <div className="text-[12px] text-[var(--ink-2)] leading-relaxed">
                        {sec.details}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* StatLine: Inline numbers separated by dividers, no boxes */}
            <div className="pt-1">
              <StatLine items={statLineItems} />
            </div>
          </div>

          {/* Emergency Alert Card with Expandable Details (Section 2.3 T5 & 5.3) */}
          {topUrgentThread && (() => {
            const contractorThread = threads.find(
              (t) =>
                t.ticketNumber === topUrgentThread.ticketNumber &&
                (t.recipientRole === "contractor" || t.id !== topUrgentThread.id)
            ) || threads.find((t) => t.id === "thread-2");

            const tenantFirstName = (topUrgentThread.senderName || "Tenant").split(" ")[0];
            const contractorFirstName = (contractorThread?.senderName || "Contractor").split(" ")[0];

            return (
              <div
                className={cn(
                  "border-l-[4px] border-l-[var(--accent)] border-y border-r border-[var(--line)] bg-[var(--pane)] rounded-r-[var(--radius-pane)] transition-all overflow-hidden shadow-2xs select-none"
                )}
              >
                {/* Main Prominent Header Bar */}
                <div className="p-4 sm:px-5 sm:py-4 flex flex-col md:flex-row md:items-center justify-between gap-3.5">
                  <div className="flex items-start sm:items-center gap-3 min-w-0">
                    <span className="font-bold text-[14px] text-[var(--accent-ink)] uppercase tracking-wider shrink-0 mt-0.5 sm:mt-0">
                      Emergency
                    </span>
                    <span className="text-[var(--line)] hidden sm:inline">·</span>
                    <div className="min-w-0">
                      <span className="text-[15px] font-semibold text-[var(--ink)] block sm:inline">
                        {topUrgentThread.unitLabel}:
                      </span>{" "}
                      <span className="text-[14px] text-[var(--ink-2)] font-medium">
                        {topUrgentThread.subject || topUrgentThread.latestSnippet}
                      </span>
                    </div>
                  </div>

                  {/* Actions & Details Dropdown Trigger */}
                  <div className="flex items-center gap-3 shrink-0 self-end md:self-center">
                    <span className="font-mono text-xs text-[var(--accent-ink)] font-bold px-2 py-0.5 rounded bg-[var(--accent)]/10 border border-[var(--accent)]/20">
                      38m SLA
                    </span>

                    <button
                      type="button"
                      onClick={() => setIsEmergencyExpanded(!isEmergencyExpanded)}
                      className="text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center gap-1 cursor-pointer py-1 px-1.5 rounded hover:bg-[var(--selected)]"
                      aria-expanded={isEmergencyExpanded}
                    >
                      <span>{isEmergencyExpanded ? "Hide details" : "Details"}</span>
                      <ChevronDown
                        className={cn(
                          "w-3.5 h-3.5 transition-transform duration-200",
                          isEmergencyExpanded && "rotate-180"
                        )}
                      />
                    </button>

                    <span className="text-[var(--line)] select-none">|</span>

                    <button
                      type="button"
                      onClick={() => router.push(`/inbox?thread=${topUrgentThread.id}`)}
                      className="text-xs font-semibold text-[var(--ink)] hover:underline underline-offset-4 cursor-pointer"
                    >
                      Reply {tenantFirstName}
                    </button>

                    {contractorThread && (
                      <button
                        type="button"
                        onClick={() => router.push(`/inbox?thread=${contractorThread.id}`)}
                        className="text-xs font-bold text-[var(--accent-ink)] hover:underline underline-offset-4 cursor-pointer"
                      >
                        Connect {contractorFirstName} →
                      </button>
                    )}
                  </div>
                </div>

                {/* Collapsible Details Drawer (Plain minimalist 2-column key/value, zero cards in cards) */}
                {isEmergencyExpanded && (
                  <div className="border-t border-[var(--line)] bg-[var(--bg)]/60 px-5 py-4 space-y-3.5 text-xs animate-in fade-in duration-150">
                    <div>
                      <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                        Reported Issue by {topUrgentThread.senderName}
                      </span>
                      <p className="text-[13px] text-[var(--ink)] italic leading-relaxed font-serif pl-3 border-l-2 border-[var(--ink-3)]">
                        "{topUrgentThread.latestSnippet}"
                      </p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
                      <div>
                        <span className="text-[var(--ink-3)] block">Assigned Contractor</span>
                        <span className="font-semibold text-[var(--ink)] text-[13px]">
                          {contractorThread?.senderName || "Chahal Bouw Electricians"}
                        </span>
                        <span className="text-[11px] text-[var(--ink-3)] block">Arrival 11:30 CET</span>
                      </div>

                      <div>
                        <span className="text-[var(--ink-3)] block">Authorized Work Order</span>
                        <span className="font-semibold text-[var(--ink)] text-[13px]">
                          PO-005 (€ 650 cap)
                        </span>
                        <span className="text-[11px] text-[var(--ink-3)] block">Lockbox PIN: 4182</span>
                      </div>

                      <div>
                        <span className="text-[var(--ink-3)] block">Recommended Protocol</span>
                        <span className="font-medium text-[var(--accent-ink)] text-[13px]">
                          Dispatch Kevin & notify tenant
                        </span>
                        <span className="text-[11px] text-[var(--ink-3)] block">Both AI drafts waiting in Inbox</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Section 1: Needs You (Top 5 threads using exact ThreadRow component, Section 5.3) */}
          <section className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title="Needs you"
                actionText="Open Inbox →"
                actionHref="/inbox"
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {needsYouThreads.length > 0 ? (
                needsYouThreads.slice(0, 5).map((t) => {
                  const rowItem: ThreadRowItem = {
                    id: t.id,
                    contactName: t.senderName,
                    channel: t.channel,
                    unit: t.unitLabel,
                    subject: t.subject || t.issueTitle || t.caseRef,
                    snippet: t.latestSnippet,
                    hasDraft: Boolean(
                      t.draftProposal?.drafts?.length ||
                      t.draftProposal?.whatsappDrafts?.length ||
                      t.draftProposal?.gmailDrafts?.length
                    ),
                    lastAt: t.receivedAt,
                    urgent: isUrgent(t),
                    status: "needs_you",
                    count: t.messages?.length || 1,
                  };

                  return (
                    <ThreadRow
                      key={t.id}
                      t={rowItem}
                      onSelect={() => router.push(`/inbox?thread=${t.id}`)}
                      onDone={() => showToast(`Thread ${t.senderName} marked as done.`)}
                      onSnooze={() => showToast(`Thread ${t.senderName} snoozed until tomorrow 09:00.`)}
                    />
                  );
                })
              ) : (
                <div className="p-6 text-center text-sm text-[var(--ink-3)]">
                  All clear. No messages currently need your action.
                </div>
              )}
            </div>
          </section>

          {/* Section 2: Waiting on others (Unresponsive cases, Section 2.3 T3 & 5.3) */}
          <section className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title="Waiting on others"
                count={radarItems.length}
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {radarItems.slice(0, 3).map((item) => {
                const isNudged = nudgedItemIds[item.id];
                return (
                  <div
                    key={item.id}
                    className="p-4 sm:px-5 sm:py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-sm hover:bg-[var(--selected)]/40 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-[var(--ink)]">
                          {item.partyName}
                        </span>
                        <span className="text-[var(--ink-3)]">·</span>
                        <span className="text-[var(--ink-2)] font-medium">
                          {item.unitLabel}
                        </span>
                        <span className="text-[var(--ink-3)]">·</span>
                        <span className="text-xs text-[var(--ink-3)]">
                          {item.subject}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--ink-3)] mt-0.5">
                        <span className="text-[var(--accent-ink)] font-medium">
                          {item.daysStalled} days stalled
                        </span>
                        <span> · {item.remindersSentCount} reminder{item.remindersSentCount > 1 ? "s" : ""} sent</span>
                      </div>
                    </div>

                    <div className="shrink-0 self-end sm:self-center">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isNudged}
                        onClick={() => handleSendNudge(item)}
                        icon={isNudged ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Send className="w-3.5 h-3.5 text-[var(--ink-3)]" />}
                        className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] shadow-2xs"
                      >
                        {isNudged ? "Nudged" : "Send nudge"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Section 3: New leads (Inquiries, Section 5.3) */}
          <section className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title="New leads"
                count={leadItems.length}
                actionText="Open all →"
                actionHref="/inbox?audience=inquiries"
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {leadItems.map((lead) => (
                <div
                  key={lead.id}
                  onClick={() => router.push("/inbox?audience=inquiries")}
                  className="p-4 sm:px-5 sm:py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-sm hover:bg-[var(--selected)]/40 transition-colors cursor-pointer select-none"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-[var(--ink)]">
                        {lead.name}
                      </span>
                      <span className="text-[var(--ink-3)]">·</span>
                      <span className="text-[var(--ink-2)] font-medium">
                        {lead.unit}
                      </span>
                      <span className="text-[var(--ink-3)]">·</span>
                      <span className="text-xs text-[var(--ink-3)] truncate max-w-sm">
                        {lead.request}
                      </span>
                    </div>
                    <div className="text-xs text-[var(--ink-3)] mt-0.5 flex items-center gap-2">
                      <span>{lead.qualification}</span>
                    </div>
                  </div>

                  <div className="shrink-0 self-end sm:self-center">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        router.push("/inbox?audience=inquiries");
                      }}
                      className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] shadow-2xs"
                    >
                      Review
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Bottom Pane: ONE pane, THREE columns separated by 1px vertical lines (Section 5.3 & 3.1) */}
          <section className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[var(--line)]">
              
              {/* Column 1: Open rent */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      Open rent
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {formatCurrency(metrics.openRentTotalEur)}
                    </span>
                  </div>

                  {/* Horizontal Segmented Progress Bar */}
                  <div className="h-2 w-full rounded-full bg-[var(--selected)] overflow-hidden flex mt-3">
                    <div style={{ width: "72.6%" }} className="bg-[var(--ink)] h-full" title="0–30 days: 72.6%" />
                    <div style={{ width: "21.3%" }} className="bg-[var(--ink-3)] h-full" title="30–90 days: 21.3%" />
                    <div style={{ width: "6.1%" }} className="bg-[var(--accent)] h-full" title="90+ days: 6.1%" />
                  </div>

                  {/* Legend */}
                  <div className="space-y-1.5 mt-3 text-xs text-[var(--ink-2)]">
                    {agingBuckets.map((b) => (
                      <div key={b.label} className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <span className={cn("w-2 h-2 rounded-full", b.barClass)} />
                          <span>{b.label}</span>
                        </div>
                        <span className="font-mono text-[var(--ink-3)] tabular-nums">{b.amount}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <Link
                  href="/money"
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1"
                >
                  <span>Review rent aging</span>
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              {/* Column 2: Occupancy */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      Occupancy
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {metrics.occupancyPercentage}%
                    </span>
                  </div>

                  {/* Bars per complex (ink bars) */}
                  <div className="space-y-2.5 mt-3 text-xs">
                    {occupancyBuildings.map((b) => (
                      <div key={b.name} className="space-y-1">
                        <div className="flex items-center justify-between text-[var(--ink-2)]">
                          <span className="truncate pr-2">{b.name}</span>
                          <span className="font-mono text-[var(--ink-3)] tabular-nums shrink-0">
                            {b.occupied}/{b.total}
                          </span>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-[var(--selected)] overflow-hidden">
                          <div
                            className="h-full bg-[var(--ink)] rounded-full transition-all"
                            style={{ width: `${b.rate}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <Link
                  href="/properties"
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1"
                >
                  <span>View 110 units directory</span>
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              {/* Column 3: Handled this week */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      Handled this week
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {metrics.autonomousActionsWeek || 142}
                    </span>
                  </div>

                  {/* 4 Items stream */}
                  <div className="space-y-2.5 mt-3 text-xs">
                    {logs.slice(0, 4).map((log) => (
                      <div key={log.id} className="flex items-start gap-2 text-xs">
                        <span className="text-[var(--ink-3)] mt-0.5">•</span>
                        <div className="min-w-0 flex-1">
                          <p className="text-[var(--ink-2)] truncate leading-snug">
                            {log.actionText}
                          </p>
                          <span className="font-mono text-[10.5px] text-[var(--ink-3)]">
                            {log.timestamp}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => showToast("Opening autonomous operations ledger...")}
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1 text-left cursor-pointer"
                >
                  <span>View autonomous ledger</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
              </div>

            </div>
          </section>

        </main>
      </div>

      {/* Floating Toast */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[#F25C05]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Ask EstateOS Panel */}
      <AskEstateOSPanel
        currentPageName="Today"
        selectedContext={`Today Briefing · ${currentNeedsYouCount} need you · ${currentUrgentCount} urgent`}
        onActionTriggered={(actionType) => {
          if (actionType === "approve_queue_item") {
            router.push("/inbox");
          } else {
            showToast(`Action dispatched from Assistant: ${actionType}`);
          }
        }}
      />

      {/* Mobile Bottom Tab Bar */}
      <MobileTabBar pendingCount={currentNeedsYouCount} />
    </div>
  );
}
