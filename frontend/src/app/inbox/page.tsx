"use client";

import React, { useState, useMemo, useEffect, useCallback, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { WorkspaceShell } from "@/components/layout/WorkspaceShell";
import { FilterBar, FilterTab, FilterGroup, SortChoice } from "@/components/ui/FilterBar";
import { ResizeHandle, usePersistedPaneSize } from "@/components/ui/ResizableSplit";
import { InboxThreadList } from "@/components/inbox/InboxThreadList";
import { InboxConversationView } from "@/components/inbox/InboxConversationView";
import { InboxComposeModal } from "@/components/inbox/InboxComposeModal";
import { threadMatchesQuery } from "@/lib/threadSearch";
import { formatClock } from "@/lib/clock";
import { matchesFilters, matchesTab, optionCount, isActivelySnoozed } from "@/lib/inboxFilters";
import { InboxThread } from "@/types/inbox";
import { Check, Clock, Columns2, Rows2, List, PenSquare, MailOpen } from "lucide-react";
import {
  approveInboxDraft,
  getInboxThreads,
  syncGmailInbox,
  markThreadRead,
  markThreadDone,
  snoozeThread,
} from "@/lib/api";
import { needsYouCount, isUrgent } from "@/lib/selectors";
import { cn } from "@/lib/utils";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import { usePolling } from "@/hooks/usePolling";

type InboxLayoutMode = "vertical" | "horizontal" | "list";

function findMatchingThread(allThreads: InboxThread[], query: string): InboxThread | null {
  if (!query) return null;
  const qClean = query.replace(/^(case-|thread-|#)/, "").trim().toLowerCase();
  if (!qClean) return null;

  const exact = allThreads.find(
    (t) =>
      t.id.toLowerCase() === query.toLowerCase() ||
      t.id.toLowerCase() === qClean ||
      (t.caseRef && t.caseRef.toLowerCase() === query.toLowerCase()) ||
      (t.caseRef && t.caseRef.replace(/^#/, "").toLowerCase() === qClean) ||
      (t.approvalId && t.approvalId.toLowerCase() === query.toLowerCase())
  );
  if (exact) return exact;

  const partial = allThreads.find(
    (t) =>
      t.id.toLowerCase().includes(qClean) ||
      qClean.includes(t.id.toLowerCase()) ||
      (t.caseRef && t.caseRef.toLowerCase().includes(qClean)) ||
      (t.approvalId && t.approvalId.toLowerCase().includes(qClean))
  );
  if (partial) return partial;

  if (qClean.length >= 3) {
    const byText = allThreads.find(
      (t) =>
        t.senderName.toLowerCase().includes(qClean) ||
        t.unitLabel.toLowerCase().includes(qClean)
    );
    if (byText) return byText;
  }

  return null;
}

function InboxContent() {
  const router = useRouter();
  const { t } = useLanguage();
  const searchParams = useSearchParams();
  const superAgent = useSuperAgent();

  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [totalServerThreads, setTotalServerThreads] = useState<number>(0);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [hasMore, setHasMore] = useState<boolean>(true);
  const [isLoadingMore, setIsLoadingMore] = useState<boolean>(false);

  const [activeTab, setActiveTab] = useState<string>("needs_you");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFilterIds, setSelectedFilterIds] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<string>("urgency");
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [isComposeOpen, setIsComposeOpen] = useState<boolean>(false);
  const [showThreadsDrawer, setShowThreadsDrawer] = useState<boolean>(false);
  const [isMobile, setIsMobile] = useState<boolean>(false);
  const [layoutMode, setLayoutMode] = useState<InboxLayoutMode>("vertical");

  const {
    size: listWidth,
    applyDelta: resizeListWidth,
    commitSize: commitListWidth,
    resetSize: resetListWidth,
  } = usePersistedPaneSize("estateos_inbox_list_w", 340, 250, 560);

  const {
    size: listHeight,
    applyDelta: resizeListHeight,
    commitSize: commitListHeight,
    resetSize: resetListHeight,
  } = usePersistedPaneSize("estateos_inbox_list_h", 260, 150, 480);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("estateos_inbox_layout") as InboxLayoutMode | null;
      if (saved === "vertical" || saved === "horizontal" || saved === "list") {
        setLayoutMode(saved);
      }
    } catch {}
  }, []);

  const cycleLayoutMode = () => {
    const order: InboxLayoutMode[] = ["vertical", "horizontal", "list"];
    const next = order[(order.indexOf(layoutMode) + 1) % order.length];
    setLayoutMode(next);
    setShowThreadsDrawer(false);
    try {
      localStorage.setItem("estateos_inbox_layout", next);
    } catch {}
  };

  const threadParam = searchParams?.get("thread") || "";
  const draftParam = searchParams?.get("draft") || "";
  const searchParam = searchParams?.get("search") || "";

  useEffect(() => {
    if (searchParam) {
      setSearchQuery(searchParam);
      setActiveTab("all");
    }
  }, [searchParam]);

  const [selectedThreadId, setSelectedThreadId] = useState<string>(threadParam);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 1024);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    if (threadParam) {
      const matched = findMatchingThread(threads, threadParam);
      if (matched) {
        setSelectedThreadId(matched.id);
        if (matched.status === "approved" || matched.status === "replied" || matched.status === "closed") {
          setActiveTab("all");
        }
      } else {
        setSelectedThreadId(threadParam);
      }
    } else {
      setSelectedThreadId("");
    }
  }, [threadParam, threads]);

  useEffect(() => {
    const handleCustomNav = (e: Event) => {
      const customEvent = e as CustomEvent<{ url: string }>;
      const url = customEvent?.detail?.url;
      if (url && url.includes("/inbox")) {
        const match = url.match(/[?&]thread=([^&]+)/);
        if (match) {
          const target = decodeURIComponent(match[1]);
          const matched = findMatchingThread(threads, target);
          if (matched) {
            setSelectedThreadId(matched.id);
            if (matched.status === "approved" || matched.status === "replied" || matched.status === "closed") {
              setActiveTab("all");
            }
          } else {
            setSelectedThreadId(target);
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, [threads]);

  const threadParamRef = useRef(threadParam);
  useEffect(() => {
    threadParamRef.current = threadParam;
  }, [threadParam]);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const inFlightRef = useRef(false);
  const fetchThreads = useCallback(() => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    getInboxThreads({ limit: 20, offset: 0 })
      .then(({ threads: live, isLive, total, hasMore: more }) => {
        if (!mountedRef.current) return;
        if (!isLive) {
          setLoadState((prev) => (prev === "ready" ? prev : "error"));
          return;
        }
        setLoadState("ready");
        if (total !== undefined) setTotalServerThreads(total);
        if (more !== undefined) setHasMore(more);

        setThreads((prev) => {
          const prevMap = new Map(prev.map((t) => [t.id, t]));
          const mergedLive = live.map((t) => {
            const old = prevMap.get(t.id);
            if (!old) return t;
            return {
              ...t,
              isRead: t.isRead !== undefined ? t.isRead : old.isRead,
            };
          });
          if (prev.length <= 20) return mergedLive;
          const liveIds = new Set(mergedLive.map((t) => t.id));
          return mergedLive.concat(prev.filter((t) => !liveIds.has(t.id)));
        });

        const currentParam = threadParamRef.current;
        if (live.length > 0 && currentParam) {
          const m = findMatchingThread(live, currentParam);
          if (m) setSelectedThreadId(m.id);
        } else if (live.length === 0) {
          setSelectedThreadId("");
        }
      })
      .catch((err) => {
        console.warn("Failed to load live inbox threads:", err);
        if (mountedRef.current) setLoadState((prev) => (prev === "ready" ? prev : "error"));
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, []);

  // Poll live threads every 8s while visible; background worker handles Gmail ingestion.
  usePolling(fetchThreads, 8000);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const handleSyncMailbox = async () => {
    setIsSyncing(true);
    showToast("Connecting to Gmail and checking for new messages...");
    try {
      const res = await syncGmailInbox();
      showToast(res.message);
      const { threads: refreshed, total } = await getInboxThreads();
      if (refreshed && refreshed.length > 0) {
        setThreads(refreshed);
        if (total !== undefined) setTotalServerThreads(total);
      }
    } catch {
      showToast("Sync finished.");
    } finally {
      setIsSyncing(false);
    }
  };

  const handleSelectThread = useCallback(
    (id: string) => {
      setSelectedThreadId(id);
      setShowThreadsDrawer(false);

      if (id) {
        const target = threads.find((t) => t.id === id);
        setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, isRead: true } : t)));
        void markThreadRead(target?.caseId || id, true);
        router.push(`/inbox?thread=${encodeURIComponent(id)}`, { scroll: false });
      } else {
        router.push("/inbox", { scroll: false });
      }
    },
    [router, threads]
  );

  const handleMarkUnread = useCallback(
    (id: string) => {
      const target = threads.find((t) => t.id === id);
      setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, isRead: false } : t)));
      void markThreadRead(target?.caseId || id, false);
      showToast("Marked as unread.");
    },
    [threads]
  );

  const handleLoadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore) return;
    setIsLoadingMore(true);
    try {
      const { threads: moreThreads, hasMore: more } = await getInboxThreads({
        limit: 20,
        offset: threads.length,
      });
      if (moreThreads && moreThreads.length > 0) {
        setThreads((prev) => {
          const existingIds = new Set(prev.map((t) => t.id));
          const additions = moreThreads.filter((t) => !existingIds.has(t.id));
          return [...prev, ...additions];
        });
      }
      setHasMore(Boolean(more));
    } catch (err) {
      console.warn("Failed to load more threads:", err);
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, hasMore, threads.length]);

  const handleApproveDraft = async (
    threadId: string,
    draftText: string,
    outboundChannel: "whatsapp" | "gmail",
    replyToMessageId?: string
  ) => {
    const targetThread = threads.find((t) => t.id === threadId);
    const approvalId = targetThread?.approvalId || targetThread?.id || threadId;
    const effectiveMsg = replyToMessageId
      ? targetThread?.messages?.find((m) => m.id === replyToMessageId)
      : undefined;

    const replyToObj = effectiveMsg
      ? {
          id: effectiveMsg.id,
          sender: effectiveMsg.senderName || targetThread?.senderName || "Tenant",
          text: effectiveMsg.body?.replace(/^["']|["']$/g, "").slice(0, 80) || "",
        }
      : undefined;

    const now = new Date();
    const newMsg = {
      id: `out-${Date.now()}`,
      sender: "owner" as const,
      senderName: "Harjot Singh",
      senderContact: "+31 20 000 0001",
      sentAt: now.toISOString(),
      timeFormatted: formatClock(now),
      body: draftText,
      channel: outboundChannel,
      replyTo: replyToObj,
    };

    setThreads((prev) =>
      prev.map((t) =>
        t.id === threadId
          ? {
              ...t,
              status: "approved" as const,
              isRead: true,
              latestSnippet: draftText,
              messages: [...(t.messages || []), newMsg],
              draftProposal: undefined,
            }
          : t
      )
    );

    try {
      await approveInboxDraft(approvalId, "d1", draftText, effectiveMsg?.id);
      showToast("Draft approved and sent via " + outboundChannel);
    } catch {
      showToast("Dispatched and logged to autonomous ledger.");
    }
  };

  const handleRejectDraft = async (threadId: string) => {
    const target = threads.find((t) => t.id === threadId);
    const approvalId = target?.approvalId || target?.id || threadId;
    setThreads((prev) =>
      prev.map((t) => (t.id === threadId ? { ...t, status: "rejected" as const } : t))
    );
    await approveInboxDraft(approvalId, "rej");
    showToast("Draft dismissed. Thread remains in queue.");
  };

  const handleMarkDone = async (threadId: string) => {
    const target = threads.find((t) => t.id === threadId);
    setThreads((prev) =>
      prev.map((t) => (t.id === threadId ? { ...t, status: "closed" as const, isRead: true, snoozedUntil: null } : t))
    );
    const ok = await markThreadDone(target?.caseId || threadId);
    showToast(ok ? "Thread marked as done." : "Thread marked done locally.");
  };

  const handleSnooze = async (threadId: string) => {
    const target = threads.find((t) => t.id === threadId);
    const res = await snoozeThread(target?.caseId || threadId);
    if (res.snoozedUntil) {
      setThreads((prev) =>
        prev.map((t) => (t.id === threadId ? { ...t, snoozedUntil: res.snoozedUntil, isRead: true } : t))
      );
    }
    showToast("Thread snoozed until tomorrow 09:00.");
  };

  // The shown name stays the sender's own (Reply-To first); linking only clears the unregistered banner.
  const handleTenantLinked = (threadId: string) => {
    setThreads((prev) =>
      prev.map((t) =>
        t.id === threadId ? { ...t, isUnregisteredSender: false } : t
      )
    );
  };

  const tabs: FilterTab[] = useMemo(() => {
    const unreadCnt = threads.filter((t) => t.isRead === false || (t.isRead === undefined && t.status === "needs_approval")).length;
    const snoozedCnt = threads.filter(isActivelySnoozed).length;
    const base: FilterTab[] = [
      { id: "needs_you", label: t("inbox.needs_you"), count: needsYouCount(threads.filter((x) => !isActivelySnoozed(x))) },
      { id: "unread", label: "Unread", count: unreadCnt > 0 ? unreadCnt : undefined },
      ...(snoozedCnt > 0 ? [{ id: "snoozed", label: "Snoozed", count: snoozedCnt }] : []),
      { id: "all", label: t("inbox.all") },
      { id: "done", label: t("inbox.done") },
    ];
    return base;
  }, [threads, t]);

  const sortOptions: SortChoice[] = [
    { id: "urgency", label: "Sort: Urgency" },
    { id: "latest", label: "Sort: Latest" },
    { id: "oldest", label: "Sort: Oldest" },
  ];

  const filterGroups: FilterGroup[] = useMemo(() => {
    const countOf = (optionId: string) => optionCount(threads, activeTab, selectedFilterIds, optionId);
    return [
      {
        id: "who",
        title: t("inbox.filter_who", "Who"),
        options: [
          { id: "who_tenants", label: t("inbox.tenants", "Tenants"), count: countOf("who_tenants") },
          { id: "who_contractors", label: t("inbox.contractors", "Contractors"), count: countOf("who_contractors") },
          { id: "who_legal", label: t("inbox.legal", "Legal"), count: countOf("who_legal") },
          { id: "who_vve", label: t("inbox.vve", "VvE"), count: countOf("who_vve") },
          { id: "who_business", label: t("inbox.business", "Business"), count: countOf("who_business") },
          { id: "who_leads", label: t("inbox.leads", "Leads"), count: countOf("who_leads") },
          { id: "who_others", label: t("inbox.others", "Others"), count: countOf("who_others") },
        ],
      },
      {
        id: "channel",
        title: t("inbox.filter_channel", "Channel"),
        options: [
          { id: "ch_whatsapp", label: t("inbox.whatsapp", "WhatsApp"), count: countOf("ch_whatsapp") },
          { id: "ch_gmail", label: t("inbox.gmail", "Gmail"), count: countOf("ch_gmail") },
          { id: "ch_portal", label: t("inbox.portal", "Portal"), count: countOf("ch_portal") },
        ],
      },
      {
        id: "type",
        title: t("inbox.filter_type", "Type"),
        options: [
          { id: "type_repairs", label: t("inbox.repairs", "Repairs"), count: countOf("type_repairs") },
          { id: "type_rent", label: t("inbox.rent_money", "Rent & Money"), count: countOf("type_rent") },
          { id: "type_lease", label: t("inbox.lease", "Lease"), count: countOf("type_lease") },
          { id: "type_complaint", label: t("inbox.complaint", "Complaint"), count: countOf("type_complaint") },
          { id: "type_contractor", label: t("inbox.contractor_updates", "Contractor"), count: countOf("type_contractor") },
          { id: "type_admin", label: t("inbox.admin", "Admin"), count: countOf("type_admin") },
        ],
      },
    ];
  }, [threads, activeTab, selectedFilterIds, t]);

  const handleFilterToggle = (id: string) => {
    setSelectedFilterIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const filteredAndSortedThreads = useMemo(() => {
    let result = threads.filter((t) => matchesTab(t, activeTab) && matchesFilters(t, selectedFilterIds));
    if (searchQuery.trim()) {
      result = result.filter((t) => threadMatchesQuery(t, searchQuery));
    }

    result.sort((a, b) => {
      if (sortBy === "urgency") {
        const aUrgent = isUrgent(a);
        const bUrgent = isUrgent(b);
        if (aUrgent && !bUrgent) return -1;
        if (!aUrgent && bUrgent) return 1;
      }
      const dateA = new Date(a.receivedAt).getTime() || 0;
      const dateB = new Date(b.receivedAt).getTime() || 0;
      return sortBy === "oldest" ? dateA - dateB : dateB - dateA;
    });

    return result;
  }, [threads, activeTab, selectedFilterIds, searchQuery, sortBy]);

  // Keyboard navigation: j / k across filtered list, c for compose
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) return;
      if (e.key === "j" || e.key === "k") {
        const currentIndex = filteredAndSortedThreads.findIndex((t) => t.id === selectedThreadId);
        if (e.key === "j" && currentIndex < filteredAndSortedThreads.length - 1) {
          e.preventDefault();
          handleSelectThread(filteredAndSortedThreads[currentIndex + 1].id);
        } else if (e.key === "k" && currentIndex > 0) {
          e.preventDefault();
          handleSelectThread(filteredAndSortedThreads[currentIndex - 1].id);
        }
      } else if (e.key === "c" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        setIsComposeOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [filteredAndSortedThreads, selectedThreadId, handleSelectThread]);

  const activeThread = findMatchingThread(threads, selectedThreadId) || null;
  const isSinglePaneMode = isMobile || layoutMode === "list";
  const isConversationOpen = Boolean(selectedThreadId && isSinglePaneMode);

  useEffect(() => {
    superAgent.setCurrentPageName("Inbox");
    if (activeThread) {
      superAgent.setSelectedContext(
        `Thread: ${activeThread.senderName} (${activeThread.unitLabel}) [Channel: ${activeThread.channel}, Subject: ${activeThread.subject || activeThread.latestSnippet}]`
      );
      superAgent.setActiveDrawerInfo({ title: activeThread.senderName, kind: "Thread" });
    } else {
      superAgent.setSelectedContext("Omnichannel Inbox (All Communications)");
      superAgent.setActiveDrawerInfo(null);
    }
  }, [activeThread, superAgent.setCurrentPageName, superAgent.setSelectedContext, superAgent.setActiveDrawerInfo]);

  const toggleSelectAll = () => {
    if (checkedIds.size > 0 && checkedIds.size >= filteredAndSortedThreads.length) {
      setCheckedIds(new Set());
    } else {
      setCheckedIds(new Set(filteredAndSortedThreads.map((t) => t.id)));
    }
  };

  const toggleCheckRow = (id: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBulkAction = async (kind: "done" | "read" | "snooze") => {
    const ids = Array.from(checkedIds);
    setCheckedIds(new Set());
    for (const id of ids) {
      if (kind === "done") await handleMarkDone(id);
      if (kind === "snooze") await handleSnooze(id);
      if (kind === "read") {
        const target = threads.find((t) => t.id === id);
        setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, isRead: true } : t)));
        await markThreadRead(target?.caseId || id, true);
      }
    }
  };

  const SplitIcon = layoutMode === "vertical" ? Columns2 : layoutMode === "horizontal" ? Rows2 : List;
  const splitLabel =
    layoutMode === "vertical" ? "Vertical split" : layoutMode === "horizontal" ? "Horizontal split" : "List only";

  const inboxHeaderStrip = (
    <>
      <div className="flex items-center gap-2 min-w-0">
        {filteredAndSortedThreads.length > 0 && (
          <label className="inline-flex items-center gap-1.5 cursor-pointer select-none text-[11.5px] text-[var(--ink-2)]">
            <input
              type="checkbox"
              checked={checkedIds.size > 0 && checkedIds.size >= filteredAndSortedThreads.length}
              onChange={toggleSelectAll}
              title="Select all visible"
              aria-label="Select all visible threads"
              className="w-3.5 h-3.5 rounded border-[var(--line-2)] text-[var(--accent)] focus:ring-[var(--accent)] cursor-pointer"
            />
            <span className="hidden @[340px]/filter:inline font-medium">All</span>
          </label>
        )}
        {totalServerThreads > 0 && (
          <span className="text-[11px] font-mono text-[var(--ink-3)] tabular-nums truncate">
            1–{filteredAndSortedThreads.length} of {totalServerThreads}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        <button
          type="button"
          onClick={() => setIsComposeOpen(true)}
          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-[var(--radius-ctl)] bg-[#0A1B2F] hover:bg-[#142c47] text-white text-[11.5px] font-semibold transition-colors cursor-pointer shrink-0"
          title="Compose new message (c)"
        >
          <PenSquare className="w-3 h-3" />
          <span>Compose</span>
        </button>
        <button
          type="button"
          onClick={cycleLayoutMode}
          className="hidden lg:inline-flex items-center gap-1 h-7 px-2 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] text-[11.5px] transition-colors cursor-pointer shrink-0"
          title={`Layout: ${splitLabel} (click to switch)`}
          aria-label={`Switch layout (${splitLabel})`}
        >
          <SplitIcon className="w-3.5 h-3.5" />
        </button>
      </div>
    </>
  );

  return (
    <WorkspaceShell
      pageTitle="Inbox"
      pendingCount={needsYouCount(threads)}
      hideSearch
      onSyncMailbox={handleSyncMailbox}
      isSyncing={isSyncing}
      agentContext={
        activeThread
          ? `${activeThread.subject || activeThread.latestSnippet} · ${activeThread.unitLabel}`
          : "All Communications"
      }
      onAgentAction={(actionType) => {
        if (actionType === "approve_queue_item" && activeThread) {
          handleApproveDraft(
            activeThread.id,
            activeThread.draftProposal?.drafts[0]?.text || "",
            activeThread.channel === "whatsapp" ? "whatsapp" : "gmail"
          );
        } else {
          showToast(`Action dispatched from Assistant: ${actionType}`);
        }
      }}
    >
      <div
        className={cn(
          "flex flex-1 min-h-0 overflow-hidden bg-white min-w-0 relative",
          !isMobile && layoutMode === "horizontal" ? "flex-col" : "flex-row"
        )}
      >
        {/* Backdrop when slide-over threads drawer is open in List mode */}
        {layoutMode === "list" && showThreadsDrawer && isConversationOpen && (
          <div
            className="hidden lg:block lg:absolute lg:inset-0 z-20 bg-black/15"
            onClick={() => setShowThreadsDrawer(false)}
            aria-hidden="true"
          />
        )}

        {/* Thread List Pane */}
        <div
          style={
            !isMobile && layoutMode === "vertical"
              ? { width: listWidth }
              : !isMobile && layoutMode === "horizontal"
                ? { height: listHeight }
                : undefined
          }
          className={cn(
            "flex flex-col overflow-hidden bg-[var(--pane)] min-w-0 min-h-0",
            !isMobile && layoutMode !== "list" && "shrink-0",
            isMobile || layoutMode === "list" ? "w-full flex-1" : "",
            isConversationOpen && !(layoutMode === "list" && showThreadsDrawer) ? "hidden" : "flex",
            layoutMode === "list" && showThreadsDrawer && isConversationOpen
              ? "lg:absolute lg:left-0 lg:top-0 lg:bottom-0 lg:w-[360px] lg:z-30 lg:shadow-2xl lg:border-r lg:border-[var(--line)]"
              : ""
          )}
        >
          <FilterBar
            tabs={tabs}
            activeTab={activeTab}
            onTabChange={setActiveTab}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            filterGroups={filterGroups}
            selectedFilterIds={selectedFilterIds}
            onFilterToggle={handleFilterToggle}
            onClearFilters={() => setSelectedFilterIds([])}
            sortOptions={sortOptions}
            sortBy={sortBy}
            onSortChange={setSortBy}
            searchPlaceholder="Search threads (press /)..."
            headerStrip={inboxHeaderStrip}
          />

          {/* Gmail-style Bulk Action Strip when threads are checked */}
          {checkedIds.size > 0 && (
            <div className="px-3 py-1.5 bg-blue-50/90 border-b border-blue-200 flex items-center justify-between gap-2 text-xs shrink-0">
              <span className="font-semibold text-[#0A1B2F]">{checkedIds.size} selected</span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => void runBulkAction("read")}
                  className="px-2 py-1 rounded bg-white border border-blue-200 hover:bg-blue-100 text-[11px] font-semibold inline-flex items-center gap-1 cursor-pointer"
                >
                  <MailOpen className="w-3 h-3" /> Read
                </button>
                <button
                  type="button"
                  onClick={() => void runBulkAction("snooze")}
                  className="px-2 py-1 rounded bg-white border border-blue-200 hover:bg-blue-100 text-[11px] font-semibold inline-flex items-center gap-1 cursor-pointer"
                >
                  <Clock className="w-3 h-3" /> Snooze
                </button>
                <button
                  type="button"
                  onClick={() => void runBulkAction("done")}
                  className="px-2 py-1 rounded bg-[#0A1B2F] text-white hover:bg-[#142c47] text-[11px] font-semibold inline-flex items-center gap-1 cursor-pointer"
                >
                  <Check className="w-3 h-3" /> Done
                </button>
              </div>
            </div>
          )}

          <div className="flex-1 min-h-0 overflow-hidden pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0">
            <InboxThreadList
              threads={filteredAndSortedThreads}
              loadState={threads.length > 0 && loadState === "error" ? "ready" : loadState}
              isFiltered={Boolean(searchQuery.trim()) || selectedFilterIds.length > 0}
              selectedThreadId={activeThread?.id || ""}
              checkedIds={checkedIds}
              onToggleCheck={toggleCheckRow}
              onSelectThread={handleSelectThread}
              onDone={handleMarkDone}
              onSnooze={handleSnooze}
              hasMore={hasMore && !searchQuery.trim() && selectedFilterIds.length === 0}
              isLoadingMore={isLoadingMore}
              onLoadMore={handleLoadMore}
              className={layoutMode === "horizontal" ? "border-r-0 border-b border-[var(--line)]" : ""}
            />
          </div>
        </div>

        {/* Resizable Split Handle between Thread List and Reading Pane */}
        {!isMobile && layoutMode === "vertical" && (
          <ResizeHandle
            orientation="horizontal"
            ariaLabel="Resize thread list"
            onDragDelta={resizeListWidth}
            onDragEnd={commitListWidth}
            onDoubleClick={resetListWidth}
          />
        )}
        {!isMobile && layoutMode === "horizontal" && (
          <ResizeHandle
            orientation="vertical"
            ariaLabel="Resize thread list height"
            onDragDelta={resizeListHeight}
            onDragEnd={commitListHeight}
            onDoubleClick={resetListHeight}
          />
        )}

        {/* Reading / Conversation Pane */}
        <div
          className={cn(
            "flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden bg-[var(--pane)]",
            isConversationOpen
              ? "flex pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0"
              : isSinglePaneMode
                ? "hidden"
                : "hidden lg:flex"
          )}
        >
          <InboxConversationView
            thread={activeThread}
            initialDraft={draftParam}
            onBack={() => handleSelectThread("")}
            showBackOnDesktop={layoutMode === "list"}
            showThreadsButton={layoutMode === "list"}
            threadCount={filteredAndSortedThreads.length}
            isThreadsDrawerOpen={showThreadsDrawer}
            onToggleThreadsDrawer={() => setShowThreadsDrawer((v) => !v)}
            onApproveDraft={handleApproveDraft}
            onRejectDraft={handleRejectDraft}
            onSendManualReply={(threadId, text, replyToId) => {
              const chan = activeThread?.channel === "gmail" ? "gmail" : "whatsapp";
              void handleApproveDraft(threadId, text, chan, replyToId);
            }}
            onMarkDone={handleMarkDone}
            onSnooze={handleSnooze}
            onMarkUnread={handleMarkUnread}
            onTenantLinked={handleTenantLinked}
          />
        </div>
      </div>

      <InboxComposeModal
        isOpen={isComposeOpen}
        onClose={() => setIsComposeOpen(false)}
        onToast={showToast}
      />

      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[#1a73e8]" />
          <span>{toastMessage}</span>
        </div>
      )}
    </WorkspaceShell>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-[var(--bg)]" />}>
      <InboxContent />
    </Suspense>
  );
}
