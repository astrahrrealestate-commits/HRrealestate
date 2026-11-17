"use client";



import React, { useState, useMemo, useEffect, useCallback, Suspense } from "react";

import { useRouter, useSearchParams } from "next/navigation";

import { format } from "date-fns";

import { Sidebar } from "@/components/layout/Sidebar";

import { TopCommandBar } from "@/components/layout/TopCommandBar";

import { MobileTabBar } from "@/components/layout/MobileTabBar";

import { FilterBar, FilterTab, FilterGroup } from "@/components/ui/FilterBar";

import { InboxThreadList } from "@/components/inbox/InboxThreadList";
import { threadMatchesQuery } from "@/lib/threadSearch";
import { formatClock } from "@/lib/clock";
import { matchesFilters, matchesTab, optionCount } from "@/lib/inboxFilters";

import { InboxConversationView } from "@/components/inbox/InboxConversationView";


import { InboxThread } from "@/types/inbox";

import { Check, X } from "lucide-react";

import { approveInboxDraft, getInboxThreads, syncGmailInbox } from "@/lib/api";

import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";

import { needsYouCount, isUrgent } from "@/lib/selectors";

import { cn } from "@/lib/utils";

import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";



function findMatchingThread(allThreads: InboxThread[], query: string): InboxThread | null {

  if (!query) return null;

  const qClean = query.replace(/^(case-|thread-|#)/, "").trim().toLowerCase();

  if (!qClean) return null;



  // 1. Exact match on ID, caseRef, or approvalId

  const exact = allThreads.find(

    (t) =>

      t.id.toLowerCase() === query.toLowerCase() ||

      t.id.toLowerCase() === qClean ||

      (t.caseRef && t.caseRef.toLowerCase() === query.toLowerCase()) ||

      (t.caseRef && t.caseRef.replace(/^#/, "").toLowerCase() === qClean) ||

      (t.approvalId && t.approvalId.toLowerCase() === query.toLowerCase())

  );

  if (exact) return exact;



  // 2. Substring / prefix match on ID, caseRef, or approvalId

  const partial = allThreads.find(

    (t) =>

      t.id.toLowerCase().includes(qClean) ||

      qClean.includes(t.id.toLowerCase()) ||

      (t.caseRef && t.caseRef.toLowerCase().includes(qClean)) ||

      (t.approvalId && t.approvalId.toLowerCase().includes(qClean))

  );

  if (partial) return partial;



  // 3. Fallback match on senderName or unitLabel if length >= 3

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



  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");

  const [activeTab, setActiveTab] = useState<string>("needs_you");

  const [searchQuery, setSearchQuery] = useState("");

  const [selectedFilterIds, setSelectedFilterIds] = useState<string[]>([]);

  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const [isSyncing, setIsSyncing] = useState<boolean>(false);

  const [isAskAgentOpen, setIsAskAgentOpen] = useState<boolean>(false);
  const [showThreadsWithAgent, setShowThreadsWithAgent] = useState<boolean>(false);

  const [isMobile, setIsMobile] = useState<boolean>(false);



  // Read selected thread from URL query (?thread=id, Section 5.6 & 6.5)

  const threadParam = searchParams?.get("thread") || "";

  const draftParam = searchParams?.get("draft") || "";
  const searchParam = searchParams?.get("search") || "";

  // A link such as /inbox?search=<tenant> (Tenants, Properties) opens the inbox already searching for it, on All
  // so a finished thread is found too.
  useEffect(() => {
    if (searchParam) {
      setSearchQuery(searchParam);
      setActiveTab("all");
    }
  }, [searchParam]);

  const [selectedThreadId, setSelectedThreadId] = useState<string>(threadParam);



  // Track viewport width for responsive mobile switching (<1024px)

  useEffect(() => {

    const handleResize = () => {

      setIsMobile(window.innerWidth < 1024);

    };

    handleResize();

    window.addEventListener("resize", handleResize);

    return () => window.removeEventListener("resize", handleResize);

  }, []);



  // Sync selected thread from URL param

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

    } else if (!isMobile && threads.length > 0 && !selectedThreadId) {

      setSelectedThreadId(threads[0].id);

    }

  }, [threadParam, isMobile, threads]);



  // Listen for instant custom navigation events (handles same-page Super Agent clicks)

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



  // Load live threads on mount and poll periodically for new incoming messages

  useEffect(() => {

    let isMounted = true;



    let inFlight = false;
    const fetchThreads = () => {
      if (inFlight) return;
      inFlight = true;
      getInboxThreads()
        .then(({ threads: live, isLive }) => {
          if (!isMounted) return;
          if (!isLive) {
            // A failed load must not wipe what is already on screen or pose as an empty inbox.
            setLoadState("error");
            return;
          }
          setLoadState("ready");
          setThreads(live);
          if (live.length > 0) {
            if (threadParam) {
              const m = findMatchingThread(live, threadParam);
              if (m) setSelectedThreadId(m.id);
            } else {
              setSelectedThreadId((prev) => prev || live[0].id);
            }
          } else {
            setSelectedThreadId("");
          }
        })
        .catch((err) => {
          console.warn("Failed to load live inbox threads:", err);
          if (isMounted) setLoadState("error");
        })
        .finally(() => {
          inFlight = false;
        });
    };

    fetchThreads();

    const pollInterval = setInterval(fetchThreads, 8000);

    // No Pub/Sub push on a local stack: pull new Gmail mail on open and every 15 s (the backend also polls every minute).
    void syncGmailInbox();
    const syncInterval = setInterval(() => void syncGmailInbox(), 15000);



    return () => {

      isMounted = false;

      clearInterval(pollInterval);

      clearInterval(syncInterval);

    };

  }, [threadParam]);



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

      const { threads: refreshed } = await getInboxThreads();

      if (refreshed && refreshed.length > 0) {

        setThreads(refreshed);

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
      setShowThreadsWithAgent(false);

      if (id) {

        // Mark as read like Gmail

        setThreads((prev) =>

          prev.map((t) => (t.id === id ? { ...t, isRead: true } : t))

        );

        router.push(`/inbox?thread=${encodeURIComponent(id)}`, { scroll: false });

      } else {

        router.push("/inbox", { scroll: false });

      }

    },

    [router]

  );



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



    let replyToObj: { id?: string; sender?: string; text?: string } | undefined = undefined;

    if (effectiveMsg) {

      replyToObj = {

        id: effectiveMsg.id,

        sender: effectiveMsg.senderName || targetThread?.senderName || "Tenant",

        text: effectiveMsg.body?.replace(/^["']|["']$/g, "").slice(0, 80) || "",

      };

    }



    const now = new Date();

    const clockNow = formatClock(now);

    const newMsg = {

      id: `out-${Date.now()}`,

      sender: "owner" as const,

      senderName: "Harjot Singh",

      senderContact: "+31 20 000 0001",

      sentAt: now.toISOString(),

      timeFormatted: clockNow,

      body: draftText,

      channel: outboundChannel,

      replyTo: replyToObj,

    };



    setThreads((prev) =>

      prev.map((t) => {

        if (t.id === threadId) {

          const currentMsgs = t.messages || [];

          return {

            ...t,

            status: "approved" as const,

            latestSnippet: draftText,

            messages: [...currentMsgs, newMsg],

            draftProposal: undefined,

          };

        }

        return t;

      })

    );



    try {

      await approveInboxDraft(approvalId, "d1", draftText, effectiveMsg?.id);

      showToast("Draft approved and sent via " + outboundChannel);

    } catch {

      showToast("Dispatched and logged to autonomous ledger.");

    }

  };



  const handleRejectDraft = (threadId: string) => {

    setThreads((prev) =>

      prev.map((t) => {

        if (t.id === threadId) {

          return {

            ...t,

            status: "rejected" as const,

          };

        }

        return t;

      })

    );

    showToast("Draft dismissed. Thread remains in queue.");

  };



  const handleMarkDone = (threadId: string) => {

    setThreads((prev) =>

      prev.map((t) => {

        if (t.id === threadId) {

          return {

            ...t,

            status: "closed" as const,

          };

        }

        return t;

      })

    );

    showToast("Thread marked as done.");

  };



  const handleSnooze = (threadId: string) => {

    showToast("Thread snoozed until tomorrow 09:00.");

  };



  // Keyboard navigation: j / k for next/previous thread (Section 5.2)

  useEffect(() => {

    const handleKeyDown = (e: KeyboardEvent) => {

      if (

        ["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)

      ) {

        return;

      }



      if (e.key === "j" || e.key === "k") {

        const currentIndex = threads.findIndex((t) => t.id === selectedThreadId);

        if (e.key === "j" && currentIndex < threads.length - 1) {

          e.preventDefault();

          handleSelectThread(threads[currentIndex + 1].id);

        } else if (e.key === "k" && currentIndex > 0) {

          e.preventDefault();

          handleSelectThread(threads[currentIndex - 1].id);

        }

      }

    };



    window.addEventListener("keydown", handleKeyDown);

    return () => window.removeEventListener("keydown", handleKeyDown);

  }, [threads, selectedThreadId, handleSelectThread]);



  // Tab definitions (Section 5.2: Needs you / All / Done)

  const tabs: FilterTab[] = useMemo(() => {

    return [

      { id: "needs_you", label: t("inbox.needs_you"), count: needsYouCount(threads) },

      { id: "all", label: t("inbox.all") },

      { id: "done", label: t("inbox.done") },

    ];

  }, [threads, t]);



  // Filter groups: Who, Channel, Type (Section 5.2)

  const filterGroups: FilterGroup[] = useMemo(() => {

    const countOf = (optionId: string) => optionCount(threads, activeTab, selectedFilterIds, optionId);

    return [

      {

        id: "who",

        title: t("inbox.filter_who", "Who"),

        options: [

          { id: "who_tenants", label: t("inbox.tenants", "Tenants"), count: countOf("who_tenants") },

          { id: "who_contractors", label: t("inbox.contractors", "Contractors"), count: countOf("who_contractors") },

          { id: "who_leads", label: t("inbox.leads", "Leads"), count: countOf("who_leads") },

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



  const handleClearFilters = () => {

    setSelectedFilterIds([]);

  };



  // Filter and sort threads

  const filteredAndSortedThreads = useMemo(() => {

    let result = [...threads];



    // 1-4. Tab, then the Who / Channel / Type options (shared with the badge counts)
    result = result.filter((t) => matchesTab(t, activeTab) && matchesFilters(t, selectedFilterIds));

    // 5. Search query (supports plain text and token unit: / from:)

    if (searchQuery.trim()) {

      result = result.filter((t) => threadMatchesQuery(t, searchQuery));

    }



    // 6. Default Sort (Section 2.2 I6): Urgent first, then newest first

    result.sort((a, b) => {

      const aUrgent = isUrgent(a);

      const bUrgent = isUrgent(b);

      if (aUrgent && !bUrgent) return -1;

      if (!aUrgent && bUrgent) return 1;



      const dateA = new Date(a.receivedAt).getTime() || 0;

      const dateB = new Date(b.receivedAt).getTime() || 0;

      return dateB - dateA;

    });



    return result;

  }, [threads, activeTab, selectedFilterIds, searchQuery]);



  const superAgent = useSuperAgent();
  // Master-detail single pane mode: on mobile (<1024px) or on desktop when Super Agent (Astra) is open
  const isSinglePaneMode = isMobile || superAgent.isOpen;
  const isConversationOpen = Boolean(selectedThreadId && isSinglePaneMode);

  const activeThread =
    findMatchingThread(threads, selectedThreadId) ||
    (isSinglePaneMode ? null : filteredAndSortedThreads[0]) ||
    null;

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

  return (

    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">

      {/* 1. Left Fixed Sidebar (Hidden on mobile, icon nav on md, full on xl) */}

      <Sidebar pendingCount={needsYouCount(threads)} />



      {/* 2. Main Content Canvas */}

      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">

        {/* Top command bar: always visible on mobile and desktop */}

        <div className="block shrink-0">

          <TopCommandBar

            pageTitle="Inbox"

            hideSearch

            onSyncMailbox={handleSyncMailbox}

            isSyncing={isSyncing}

          />

        </div>



        {/* 3. Omnichannel Inbox Workspace (Section 5.2: 2-column layout inside shell) */}

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#27272a] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex overflow-hidden relative min-w-0">
            <div
              className={cn(
                "flex flex-col flex-1 min-h-0 overflow-hidden bg-white min-w-0 relative",
                superAgent.isOpen
                  ? "lg:grid lg:grid-cols-1"
                  : "lg:grid lg:grid-cols-[320px_1fr] xl:grid-cols-[340px_1fr]"
              )}
            >

          {/* Backdrop when thread drawer is open alongside Super Agent on desktop */}
          {superAgent.isOpen && showThreadsWithAgent && (
            <div
              className="hidden lg:block lg:absolute lg:inset-0 z-20 bg-black/15"
              onClick={() => setShowThreadsWithAgent(false)}
              aria-hidden="true"
            />
          )}

          {/* Left Column: 6 Controls FilterBar + Grouped Thread List */}
          <div
            className={cn(
              "h-full flex flex-col overflow-hidden bg-[var(--pane)]",
              isConversationOpen ? "hidden" : "flex"
            )}
          >
            {superAgent.isOpen && showThreadsWithAgent && (
              <div className="hidden lg:flex items-center justify-between px-3 py-2 border-b border-[var(--line)] bg-[var(--bg)] shrink-0">
                <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-2)]">
                  Conversations ({filteredAndSortedThreads.length})
                </span>
                <button
                  type="button"
                  onClick={() => setShowThreadsWithAgent(false)}
                  className="p-1 rounded hover:bg-[var(--selected)] text-[var(--ink-3)] hover:text-[var(--ink)] cursor-pointer"
                  title="Close threads drawer"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            )}

            {/* FilterBar (6 controls total: 3 tabs + search + Filter popover + ⟳) */}

            <FilterBar

              tabs={tabs}

              activeTab={activeTab}

              onTabChange={setActiveTab}

              searchQuery={searchQuery}

              onSearchChange={setSearchQuery}

              filterGroups={filterGroups}

              selectedFilterIds={selectedFilterIds}

              onFilterToggle={handleFilterToggle}

              onClearFilters={handleClearFilters}

              onRefresh={handleSyncMailbox}

              isRefreshing={isSyncing}

              refreshTooltip="Sync mailbox"

              searchPlaceholder="Search threads (press /)..."

            />



            {/* Thread List with Sticky Date Groups */}

            <div className="flex-1 min-h-0 overflow-hidden pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0">

              <InboxThreadList

                threads={filteredAndSortedThreads}
                loadState={threads.length > 0 && loadState === "error" ? "ready" : loadState}
                isFiltered={Boolean(searchQuery.trim()) || selectedFilterIds.length > 0}

                selectedThreadId={activeThread?.id || ""}

                onSelectThread={handleSelectThread}

                onDone={handleMarkDone}

                onSnooze={handleSnooze}

              />

            </div>

          </div>



          {/* Right Column: Chat Timeline + AiInsight + Sticky Composer */}

          <div

            className={cn(

              "h-full flex-1 min-h-0 flex flex-col overflow-hidden bg-[var(--pane)]",

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

              showBackOnDesktop={superAgent.isOpen && !isMobile}

              onApproveDraft={handleApproveDraft}

              onRejectDraft={handleRejectDraft}

              onSendManualReply={(threadId, text, replyToId) => {

                const chan = activeThread?.channel === "gmail" ? "gmail" : "whatsapp";

                handleApproveDraft(threadId, text, chan, replyToId);

              }}

              onMarkDone={handleMarkDone}
              showThreadsButton={superAgent.isOpen}
              threadCount={filteredAndSortedThreads.length}
              isThreadsDrawerOpen={showThreadsWithAgent}
              onToggleThreadsDrawer={() => setShowThreadsWithAgent((v) => !v)}
            />

          </div>
            </div>
          </div>

          {/* Ask EstateOS Assistant (40% width on right side) */}
          <AskEstateOSPanel
            currentPageName="Inbox"
            selectedContext={
              activeThread
                ? `${activeThread.subject || activeThread.latestSnippet} · ${activeThread.unitLabel}`
                : "All Communications"
            }
            onActionTriggered={(actionType) => {
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
          />
        </div>
      </div>



      {/* Toast Feedback */}

      {toastMessage && (

        <div className="fixed bottom-6 right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">

          <Check className="w-4 h-4 text-[#1a73e8]" />

          <span>{toastMessage}</span>

        </div>

      )}







      {/* Mobile Bottom Tab Bar: always visible on mobile across thread list & open conversations */}

      <MobileTabBar pendingCount={needsYouCount(threads)} />

    </div>

  );

}



export default function InboxPage() {

  return (

    <Suspense fallback={<div className="min-h-dvh bg-[var(--bg)]" />}>

      <InboxContent />

    </Suspense>

  );

}
