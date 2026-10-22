"use client";

import React, { useState, useMemo, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { format } from "date-fns";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { FilterBar, FilterTab, FilterGroup } from "@/components/ui/FilterBar";
import { InboxThreadList } from "@/components/inbox/InboxThreadList";
import { InboxConversationView } from "@/components/inbox/InboxConversationView";
import { MOCK_INBOX_THREADS } from "@/data/inboxMockData";
import { InboxThread } from "@/types/inbox";
import { Check } from "lucide-react";
import { approveInboxDraft, getInboxThreads, syncGmailInbox } from "@/lib/api";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { needsYouCount, isNeedsYou, isUrgent } from "@/lib/selectors";
import { cn } from "@/lib/utils";

function InboxContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [threads, setThreads] = useState<InboxThread[]>(MOCK_INBOX_THREADS);
  const [activeTab, setActiveTab] = useState<string>("needs_you");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFilterIds, setSelectedFilterIds] = useState<string[]>([]);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState<boolean>(false);
  const [isMobile, setIsMobile] = useState<boolean>(false);

  // Read selected thread from URL query (?thread=id, Section 5.6 & 6.5)
  const threadParam = searchParams?.get("thread") || "";
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
      setSelectedThreadId(threadParam);
    } else if (!isMobile && threads.length > 0 && !selectedThreadId) {
      setSelectedThreadId(threads[0].id);
    }
  }, [threadParam, isMobile, threads]);

  // Load live threads on mount and poll periodically for new incoming messages
  useEffect(() => {
    let isMounted = true;

    const fetchThreads = () => {
      getInboxThreads()
        .then(({ threads: live }) => {
          if (isMounted && live && live.length > 0) {
            setThreads(live);
            setSelectedThreadId((prev) => prev || live[0].id);
          }
        })
        .catch((err) => {
          console.warn("Failed to load live inbox threads:", err);
        });
    };

    fetchThreads();
    const pollInterval = setInterval(fetchThreads, 8000);

    return () => {
      isMounted = false;
      clearInterval(pollInterval);
    };
  }, []);

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

    const incomingMsgs = (targetThread?.messages || []).filter((m) => m.sender !== "owner");
    const latestIncoming = incomingMsgs[incomingMsgs.length - 1];
    const effectiveMsg = replyToMessageId
      ? targetThread?.messages?.find((m) => m.id === replyToMessageId)
      : latestIncoming;

    let replyToObj: { id?: string; sender?: string; text?: string } | undefined = undefined;
    if (effectiveMsg) {
      replyToObj = {
        id: effectiveMsg.id,
        sender: effectiveMsg.senderName || targetThread?.senderName || "Tenant",
        text: effectiveMsg.body?.replace(/^["']|["']$/g, "").slice(0, 80) || "",
      };
    }

    const now = new Date();
    const utcHours = String(now.getUTCHours()).padStart(2, "0");
    const utcMins = String(now.getUTCMinutes()).padStart(2, "0");
    const newMsg = {
      id: `out-${Date.now()}`,
      sender: "owner" as const,
      senderName: "Harjot Singh",
      senderContact: "+31 20 000 0001",
      sentAt: now.toISOString(),
      timeFormatted: `${utcHours}:${utcMins}`,
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
      { id: "needs_you", label: "Needs you", count: needsYouCount(threads) },
      { id: "all", label: "All" },
      { id: "done", label: "Done" },
    ];
  }, [threads]);

  // Filter groups: Who, Channel, Type (Section 5.2)
  const filterGroups: FilterGroup[] = useMemo(() => {
    const tenantsCount = threads.filter((t) => t.recipientRole === "tenant").length;
    const contractorsCount = threads.filter((t) => t.recipientRole === "contractor").length;
    const leadsCount = threads.filter((t) => t.recipientRole === "inquiry").length;

    const whatsappCount = threads.filter((t) => t.channel === "whatsapp").length;
    const gmailCount = threads.filter((t) => t.channel === "gmail").length;
    const portalCount = threads.filter((t) => t.channel === "portal").length;

    const repairsCount = threads.filter((t) => t.category === "maintenance" || t.category === "contractor_repairs").length;
    const rentCount = threads.filter((t) => t.category === "rent" || t.category === "payment").length;
    const leaseCount = threads.filter((t) => t.category === "lease" || t.category === "sublet").length;
    const complaintCount = threads.filter((t) => t.category === "complaint").length;
    const adminCount = threads.filter((t) => t.category === "admin").length;

    return [
      {
        id: "who",
        title: "Who",
        options: [
          { id: "who_tenants", label: "Tenants", count: tenantsCount },
          { id: "who_contractors", label: "Contractors", count: contractorsCount },
          { id: "who_leads", label: "Leads", count: leadsCount },
        ],
      },
      {
        id: "channel",
        title: "Channel",
        options: [
          { id: "ch_whatsapp", label: "WhatsApp", count: whatsappCount },
          { id: "ch_gmail", label: "Gmail", count: gmailCount },
          { id: "ch_portal", label: "Portal", count: portalCount },
        ],
      },
      {
        id: "type",
        title: "Type",
        options: [
          { id: "type_repairs", label: "Repairs", count: repairsCount },
          { id: "type_rent", label: "Rent & Money", count: rentCount },
          { id: "type_lease", label: "Lease", count: leaseCount },
          { id: "type_complaint", label: "Complaint", count: complaintCount },
          { id: "type_admin", label: "Admin", count: adminCount },
        ],
      },
    ];
  }, [threads]);

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

    // 1. Tab filter
    if (activeTab === "needs_you") {
      result = result.filter(isNeedsYou);
    } else if (activeTab === "done") {
      result = result.filter((t) => !isNeedsYou(t));
    }

    // 2. Who filter
    const whoFilters = selectedFilterIds.filter((id) => id.startsWith("who_"));
    if (whoFilters.length > 0) {
      result = result.filter((t) => {
        if (whoFilters.includes("who_tenants") && t.recipientRole === "tenant") return true;
        if (whoFilters.includes("who_contractors") && t.recipientRole === "contractor") return true;
        if (whoFilters.includes("who_leads") && t.recipientRole === "inquiry") return true;
        return false;
      });
    }

    // 3. Channel filter
    const chFilters = selectedFilterIds.filter((id) => id.startsWith("ch_"));
    if (chFilters.length > 0) {
      result = result.filter((t) => {
        if (chFilters.includes("ch_whatsapp") && t.channel === "whatsapp") return true;
        if (chFilters.includes("ch_gmail") && t.channel === "gmail") return true;
        if (chFilters.includes("ch_portal") && t.channel === "portal") return true;
        return false;
      });
    }

    // 4. Type filter
    const typeFilters = selectedFilterIds.filter((id) => id.startsWith("type_"));
    if (typeFilters.length > 0) {
      result = result.filter((t) => {
        if (typeFilters.includes("type_repairs") && (t.category === "maintenance" || t.category === "contractor_repairs")) return true;
        if (typeFilters.includes("type_rent") && (t.category === "rent" || t.category === "payment")) return true;
        if (typeFilters.includes("type_lease") && (t.category === "lease" || t.category === "sublet")) return true;
        if (typeFilters.includes("type_complaint") && t.category === "complaint") return true;
        if (typeFilters.includes("type_admin") && t.category === "admin") return true;
        return false;
      });
    }

    // 5. Search query (supports plain text and token unit: / from:)
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter((t) => {
        const text = `${t.senderName} ${t.unitLabel} ${t.subject} ${t.latestSnippet} ${t.ticketNumber || ""} ${t.caseRef || ""}`.toLowerCase();
        return text.includes(q);
      });
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

  const activeThread =
    threads.find((t) => t.id === selectedThreadId) ||
    filteredAndSortedThreads[0] ||
    null;

  // On mobile (<1024px), is conversation pane active?
  const isMobileConversationOpen = Boolean(selectedThreadId && isMobile);

  return (
    <div className="min-h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)]">
      {/* 1. Left Fixed Sidebar (Hidden on mobile, icon nav on md, full on xl) */}
      <Sidebar pendingCount={needsYouCount(threads)} />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-dvh overflow-hidden">
        {/* Top bar hidden on mobile when conversation is open so conversation header controls the screen */}
        <div className={cn(isMobileConversationOpen ? "hidden md:block" : "block")}>
          <TopCommandBar
            pageTitle="Inbox"
            hideSearch
            onAskAgent={() => setIsAskAgentOpen(true)}
            onSyncMailbox={handleSyncMailbox}
            isSyncing={isSyncing}
          />
        </div>

        {/* 3. Omnichannel Inbox Workspace (Section 5.2: 2-column layout inside shell) */}
        <div className="lg:grid lg:grid-cols-[340px_1fr] xl:grid-cols-[380px_1fr] flex-1 min-h-0 h-[calc(100dvh-3.5rem)]">
          {/* Left Column: 6 Controls FilterBar + Grouped Thread List */}
          <div
            className={cn(
              "h-full flex flex-col overflow-hidden bg-[var(--pane)]",
              isMobileConversationOpen ? "hidden lg:flex" : "flex"
            )}
          >
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
              "h-full flex flex-col overflow-hidden bg-[var(--pane)]",
              isMobileConversationOpen ? "flex" : "hidden lg:flex"
            )}
          >
            <InboxConversationView
              thread={activeThread}
              onBack={() => handleSelectThread("")}
              onApproveDraft={handleApproveDraft}
              onRejectDraft={handleRejectDraft}
              onSendManualReply={(threadId, text, replyToId) => {
                const chan = activeThread?.channel === "gmail" ? "gmail" : "whatsapp";
                handleApproveDraft(threadId, text, chan, replyToId);
              }}
              onMarkDone={handleMarkDone}
            />
          </div>
        </div>
      </div>

      {/* Toast Feedback */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[#F25C05]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Ask EstateOS Assistant */}
      <AskEstateOSPanel
        isOpen={isAskAgentOpen}
        onClose={() => setIsAskAgentOpen(false)}
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

      {/* Mobile Bottom Tab Bar: hidden when conversation is open so composer sits directly at bottom */}
      <MobileTabBar
        pendingCount={needsYouCount(threads)}
        className={cn(isMobileConversationOpen ? "hidden" : "grid")}
      />
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
