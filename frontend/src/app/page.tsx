"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatLongDay } from "@/lib/clock";
import { ArrowRight, Check, Send, AlertTriangle, ShieldCheck, ChevronDown, Ticket, Wrench, Mail, MessageSquare, Pencil, Clock, Shield } from "lucide-react";
import { AstraIcon } from "@/components/ui/AstraBrand";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { ThreadRow, ThreadRowItem } from "@/components/ui/ThreadRow";
import { StatLine, StatItem } from "@/components/ui/StatLine";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { CalendarApprovalsCard } from "@/components/today/CalendarApprovalsCard";
import { Button } from "@/components/ui/Button";
import { formatCurrency, cn } from "@/lib/utils";
import { useLanguage } from "@/context/LanguageContext";
import {
  getInboxThreads,
  markThreadDone,
  snoozeThread,
  getDashboardPulse,
  getDashboardRadar,
  getDashboardAttention,
  type AttentionItem,
  getDashboardInquiries,
  getAutonomousLogs,
  getDashboardBriefing,
  syncGmailInbox,
  approveInboxDraft,
  approveMaintenanceTicket,
  getMaintenanceTickets,
  updateMaintenanceTicket,
  MaintenanceTicket,
  ProspectiveInquiry,
} from "@/lib/api";
import { EditTicketModal } from "@/components/maintenance/EditTicketModal";
import { StalledItem, INITIAL_STALLED_ITEMS } from "@/components/today/UnresponsiveRadarCard";
import { BrixxAttentionCard } from "@/components/today/BrixxAttentionCard";
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
import { useAuth } from "@/context/AuthContext";
import { getPortfolio, getTenantProfiles } from "@/lib/portfolioApi";
import type { TenantProfile } from "@/types/portfolio";
import type { PropertyComplex } from "@/types/portfolio";
import { ticketRef } from "@/lib/caseRef";


export default function TodayPage() {
  const router = useRouter();
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  // State
  const [threads, setThreads] = useState<InboxThread[]>([]);
  const [metrics, setMetrics] = useState<PulseMetrics>(INITIAL_METRICS);
  const [portfolio, setPortfolio] = useState<PropertyComplex[] | null>(null);
  const [tenants, setTenants] = useState<TenantProfile[] | null>(null);
  const [radarItems, setRadarItems] = useState<StalledItem[]>([]);
  const [attention, setAttention] = useState<{ items: AttentionItem[]; total: number; urgentCount: number }>({
    items: [],
    total: 0,
    urgentCount: 0,
  });
  const [inquiries, setInquiries] = useState<ProspectiveInquiry[]>([]);
  const [logs, setLogs] = useState<AutonomousActionLog[]>([]);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);
  const [isEmergencyExpanded, setIsEmergencyExpanded] = useState<boolean>(true);
  const [mobileEmergencyOpen, setMobileEmergencyOpen] = useState<boolean>(false);
  const [mobileEmergencyTab, setMobileEmergencyTab] = useState<"tenant" | "contractor">("tenant");
  const [mobileBriefingTextExpanded, setMobileBriefingTextExpanded] = useState<boolean>(false);
  const [nudgedItemIds, setNudgedItemIds] = useState<Record<string, boolean>>({});
  const [showAllUrgent, setShowAllUrgent] = useState<boolean>(false);
  const [showAllNeedsYou, setShowAllNeedsYou] = useState<boolean>(false);
  const [activeSection, setActiveSection] = useState<"all" | "urgent" | "needs_you" | "waiting" | "leads" | "calendar" | "overview">("all");

  // Maintenance in-place state
  const DEFAULT_TICKET_TEMPLATE: MaintenanceTicket = useMemo(() => ({
    id: "m-new",
    ticketNumber: "#001",
    issueTitle: "Maintenance Request",
    unitLabel: "Unit",
    tenantName: "Tenant",
    tenantPhone: "",
    category: "appliance",
    contractorName: "",
    contractorTrade: "",
    contractorPhone: "",
    urgency: "normal",
    status: "pending_approval",
    slaRemaining: "",
    isOverdue: false,
    poBudgetCap: "",
    reportedAt: "Today",
    notes: "",
    originalMessage: "",
    contractorDraft: "",
    tenantDraft: "",
  }), []);

  const [maintenanceTickets, setMaintenanceTickets] = useState<MaintenanceTicket[]>([]);
  const [activeEditTicket, setActiveEditTicket] = useState<MaintenanceTicket | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [tenantReplySentMap, setTenantReplySentMap] = useState<Record<string, boolean>>({});
  const [contractorDispatchedMap, setContractorDispatchedMap] = useState<Record<string, boolean>>({});
  const [customTenantReplyText, setCustomTenantReplyText] = useState<Record<string, string>>({});
  const [customContractorText, setCustomContractorText] = useState<Record<string, string>>({});

  // Fetch live threads and dashboard data (critical above-the-fold first; secondary widgets staggered)
  useEffect(() => {
    let isMounted = true;

    // 1. Inbox threads (summary mode without unused HTML email bodies cuts Dashboard payload by ~90%)
    getInboxThreads({ limit: 100, sort: "priority", includeHtml: false })
      .then(({ threads: live }) => {
        if (isMounted) {
          setThreads(live || []);
        }
      })
      .catch((err) => console.warn("Failed to load threads on Today:", err));

    getDashboardPulse()
      .then((pRes) => {
        if (isMounted && pRes.isLive) setMetrics(pRes.metrics);
      })
      .catch((err) => console.warn("Failed to load pulse:", err));

    // BRIXX: open tickets, overdue rent and ending leases, so Today has content without Gmail or WhatsApp
    getDashboardAttention().then((result) => {
      if (isMounted) setAttention(result);
    });

    // Maintenance tickets for in-place detail view and editing
    getMaintenanceTickets()
      .then((mRes) => {
        if (!isMounted) return;
        if (mRes.isLive) {
          setMaintenanceTickets(mRes.tickets || []);
        }
      })
      .catch((err) => console.warn("Failed to load maintenance tickets:", err));

    // Stagger secondary portfolio/directory/auxiliary fetches slightly so critical calls get priority
    const secondaryTimer = setTimeout(() => {
      if (!isMounted) return;
      getPortfolio().then((result) => {
        if (isMounted && result.ok) setPortfolio(result.data);
      });
      getTenantProfiles().then((result) => {
        if (isMounted && result.ok) setTenants(result.data);
      });
      Promise.all([getDashboardRadar(), getDashboardInquiries(), getAutonomousLogs()])
        .then(([rRes, iRes, lRes]) => {
          if (!isMounted) return;
          if (rRes.isLive) setRadarItems(rRes.items || []);
          if (iRes.isLive) setInquiries(iRes.inquiries || []);
          if (lRes.isLive) setLogs(lRes.logs || []);
        })
        .catch((err) => console.warn("Failed to load auxiliary dashboard data:", err));
    }, 180);

    return () => {
      isMounted = false;
      clearTimeout(secondaryTimer);
    };
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const handleSaveTicket = async (updatedTicket: MaintenanceTicket) => {
    try {
      await updateMaintenanceTicket(updatedTicket.id || updatedTicket.ticketNumber, updatedTicket);
      setMaintenanceTickets((prev) =>
        prev.map((t) => (t.ticketNumber === updatedTicket.ticketNumber ? updatedTicket : t))
      );
      showToast(`Ticket ${updatedTicket.ticketNumber} updated successfully.`);
    } catch {
      showToast(`Ticket ${updatedTicket.ticketNumber} updated locally.`);
    }
    setIsEditModalOpen(false);
  };

  // In-flight action lock ref to prevent rapid multiple clicks (Rows 42, 43)
  const actionLockRef = React.useRef<Record<string, boolean>>({});

  const handleSendTenantReply = async (
    ticket: MaintenanceTicket,
    channel: "whatsapp" | "gmail" | string,
    key?: string
  ) => {
    const targetKey = key || ticket.id || ticket.ticketNumber;
    if (actionLockRef.current[`reply-${targetKey}`]) return;

    // Row 36: Check that outgoing reply is not empty
    const matchedThread =
      threads.find(
        (t) =>
          t.id === targetKey ||
          t.caseId === ticket.id ||
          t.ticketNumber === ticket.ticketNumber ||
          t.id === ticket.id
      ) || topUrgentThread;
    const channelDraftFallback =
      (channel === "whatsapp"
        ? matchedThread?.draftProposal?.whatsappDrafts?.[0]?.text
        : matchedThread?.draftProposal?.gmailDrafts?.[0]?.text) ||
      matchedThread?.draftProposal?.drafts?.[0]?.text ||
      "";
    const explicitDraft =
      customTenantReplyText[targetKey] ?? customTenantReplyText[ticket.ticketNumber];
    const currentText =
      explicitDraft ?? ((ticket.tenantDraft?.trim() ? ticket.tenantDraft : "") || channelDraftFallback);
    if (explicitDraft !== undefined && !explicitDraft.trim()) {
      showToast("Cannot send an empty reply. Please enter a message.");
      return;
    }
    if (!currentText.trim()) {
      showToast("Cannot send an empty reply. Please enter a message.");
      return;
    }

    actionLockRef.current[`reply-${targetKey}`] = true;
    setTenantReplySentMap((prev) => ({ ...prev, [targetKey]: true }));

    // Copy draft message to clipboard so user can paste immediately in Gmail or WhatsApp
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(currentText.trim());
      } catch {
        // Non-fatal if clipboard permission blocked
      }
    }

    // Helper to extract or decode direct Gmail thread ID
    const getGmailThreadId = (threadOrKey?: string | null): string | null => {
      if (!threadOrKey) return null;
      // 1. Direct hex thread id (e.g. 18b2f90a12345678 or 16-20 hex characters)
      if (/^[a-f0-9]{16,20}$/i.test(threadOrKey)) {
        return threadOrKey;
      }
      // 2. Decode base64 thread_key ("gmail:...")
      try {
        const padded = threadOrKey.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (threadOrKey.length % 4)) % 4);
        const decoded = typeof window !== "undefined" ? window.atob(padded) : Buffer.from(padded, "base64").toString("utf-8");
        if (decoded.startsWith("gmail:")) {
          const ref = decoded.slice(6);
          if (/^[a-f0-9]{16,20}$/i.test(ref)) {
            return ref;
          }
        }
      } catch {
        // Not base64
      }
      return null;
    };

    // Open channel-specific reply window (Gmail reply chain / compose, or WhatsApp)
    const tenantContact = matchedThread?.senderContact || ticket.tenantPhone || "vipint9902@gmail.com";
    const isEmail = channel === "gmail" || tenantContact.includes("@");

    if (isEmail) {
      const gmailThreadId =
        getGmailThreadId(matchedThread?.externalThreadId) ||
        getGmailThreadId(matchedThread?.id) ||
        getGmailThreadId((matchedThread as any)?.thread_key);

      if (gmailThreadId) {
        // Open the existing conversation thread in Gmail directly
        const gmailThreadUrl = `https://mail.google.com/mail/u/0/#inbox/${gmailThreadId}`;
        window.open(gmailThreadUrl, "_blank");
        showToast(`Draft copied to clipboard & opened Gmail reply chain for ${ticket.tenantName}.`);
      } else {
        // New email or no external thread ID: open Gmail compose with subject and prefilled body
        const subject = matchedThread?.subject
          ? matchedThread.subject.toLowerCase().startsWith("re:")
            ? matchedThread.subject
            : `Re: ${matchedThread.subject}`
          : `Re: Maintenance ${ticket.ticketNumber} - ${ticket.unitLabel}`;
        const gmailComposeUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(tenantContact)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(currentText.trim())}`;
        window.open(gmailComposeUrl, "_blank");
        showToast(`Draft copied to clipboard & opened Gmail compose for ${ticket.tenantName}.`);
      }
    } else {
      const cleanPhone = tenantContact.replace(/[^0-9]/g, "");
      const waUrl = cleanPhone
        ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(currentText.trim())}`
        : `https://web.whatsapp.com/send?text=${encodeURIComponent(currentText.trim())}`;
      window.open(waUrl, "_blank");
      showToast(`Draft copied to clipboard & opened in WhatsApp for ${ticket.tenantName}.`);
    }

    // Mark thread as approved in local UI state without silent backend sending
    setThreads((prev) =>
      prev.map((t) =>
        t.id === targetKey || t.ticketNumber === ticket.ticketNumber
          ? { ...t, status: "approved" as const }
          : t
      )
    );

    setTimeout(() => {
      delete actionLockRef.current[`reply-${targetKey}`];
    }, 1200);
  };

  const handleDispatchContractor = async (
    ticket: MaintenanceTicket,
    key?: string
  ) => {
    const targetKey = key || ticket.id || ticket.ticketNumber;
    if (actionLockRef.current[`dispatch-${targetKey}`]) return;

    const contractorPhone = ticket.contractorPhone?.trim() || "";
    const contractorEmail = ticket.contractorEmail?.trim() || "";
    if (!contractorPhone && !contractorEmail) {
      showToast("No contractor contact assigned. Add contractor details first.");
      setActiveEditTicket(ticket);
      setIsEditModalOpen(true);
      return;
    }

    // Row 37: Check that work order details are not empty
    const currentOrder = customContractorText[ticket.ticketNumber] ?? ticket.contractorDraft ?? "";
    if (customContractorText[ticket.ticketNumber] !== undefined && !customContractorText[ticket.ticketNumber].trim()) {
      showToast("Cannot dispatch empty work order. Please enter details.");
      return;
    }
    if (!currentOrder.trim()) {
      showToast("Cannot dispatch empty work order. Please enter details.");
      return;
    }

    actionLockRef.current[`dispatch-${targetKey}`] = true;
    setContractorDispatchedMap((prev) => ({ ...prev, [targetKey]: true }));
    // Copy work order to clipboard
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(currentOrder.trim());
      } catch {
        // Non-fatal
      }
    }

    // Persist work order text to ticket if changed
    try {
      await updateMaintenanceTicket(ticket.ticketNumber, {
        contractorDraft: currentOrder.trim(),
      });
      await approveMaintenanceTicket(ticket.id || ticket.ticketNumber, {
        dispatchContractor: true,
        notifyTenant: false,
        poBudgetCap: ticket.poBudgetCap,
      });
    } catch {
      // Graceful
    }

    // Open Contractor Channel (WhatsApp or Email) for human review and dispatch
    if (contractorPhone) {
      const cleanPhone = contractorPhone.replace(/[^0-9]/g, "");
      const waUrl = cleanPhone
        ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(currentOrder.trim())}`
        : `https://web.whatsapp.com/send?text=${encodeURIComponent(currentOrder.trim())}`;
      window.open(waUrl, "_blank");
      showToast(`Work order copied to clipboard & opened in WhatsApp for ${ticket.contractorName || "Contractor"}.`);
    } else if (contractorEmail) {
      const subject = `Work Order ${ticket.ticketNumber} - ${ticket.unitLabel} [Cap: ${ticket.poBudgetCap}]`;
      const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(contractorEmail)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(currentOrder.trim())}`;
      window.open(gmailUrl, "_blank");
      showToast(`Work order copied to clipboard & opened in Gmail for ${ticket.contractorName || "Contractor"}.`);
    }

    setTimeout(() => {
      delete actionLockRef.current[`dispatch-${targetKey}`];
    }, 1200);
  };

  const handleApproveBoth = async (
    ticket: MaintenanceTicket,
    channel: "whatsapp" | "gmail" | string,
    key?: string
  ) => {
    const targetKey = key || ticket.id || ticket.ticketNumber;
    setContractorDispatchedMap((prev) => ({ ...prev, [targetKey]: true }));
    setTenantReplySentMap((prev) => ({ ...prev, [targetKey]: true }));
    showToast(`Ticket ${ticket.ticketNumber}: Dispatched to ${ticket.contractorName} & replied via ${channel === "whatsapp" ? "WhatsApp" : "Email"}.`);
    try {
      await approveMaintenanceTicket(ticket.id || ticket.ticketNumber, {
        dispatchContractor: true,
        notifyTenant: true,
        poBudgetCap: ticket.poBudgetCap,
      });
    } catch {
      // Graceful
    }

    setTimeout(() => {
      delete actionLockRef.current[`dispatch-${targetKey}`];
    }, 1200);
  };

  const handleSendNudge = async (item: StalledItem) => {
    if (actionLockRef.current[`nudge-${item.id}`]) return;
    actionLockRef.current[`nudge-${item.id}`] = true;
    setNudgedItemIds((prev) => ({ ...prev, [item.id]: true }));

    const reminderText =
      item.proposedActionDraft ||
      `Beste ${item.partyName}, vriendelijke herinnering over ${item.subject} voor ${item.unitLabel}. Graag vernemen wij je reactie. Met vriendelijke groet, Harjot (EstateOS)`;

    // Copy reminder text to clipboard
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(reminderText.trim());
      } catch {
        // Non-fatal
      }
    }

    if (item.contact.includes("@")) {
      const subject = `Herinnering: ${item.subject} (${item.unitLabel})`;
      const gmailUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(item.contact)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(reminderText.trim())}`;
      window.open(gmailUrl, "_blank");
      showToast(`Nudge copied to clipboard & opened in Gmail for ${item.partyName}.`);
    } else {
      const cleanPhone = item.contact.replace(/[^0-9]/g, "");
      const waUrl = cleanPhone
        ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(reminderText.trim())}`
        : `https://web.whatsapp.com/send?text=${encodeURIComponent(reminderText.trim())}`;
      window.open(waUrl, "_blank");
      showToast(`Nudge copied to clipboard & opened in WhatsApp for ${item.partyName}.`);
    }

    setTimeout(() => {
      delete actionLockRef.current[`nudge-${item.id}`];
    }, 1200);
  };

  // Selectors: Single source of truth (Section 2.5 D1 & 6.4)
  const currentNeedsYouCount = needsYouCount(threads);
  // Exclude unconfirmed rent invoices (settled in Exact Online) from urgent count so real emergencies take center stage
  const urgentAttentionCount = attention.items.filter((i) => i.urgent && i.kind !== "rent").length;
  const currentUrgentCount = urgentCount(threads) + urgentAttentionCount;
  const urgentThreads = urgent(threads);
  const needsYouThreads = needsYou(threads);

  // Top urgent thread for emergency alert card; remaining urgent threads render as compact rows
  const topUrgentThread = urgentThreads[0] || null;
  const otherUrgentThreads = urgentThreads.slice(1);

  const handleDoneThread = async (thread: InboxThread) => {
    const caseId = thread.caseId || thread.id;
    const prevStatus = thread.status;
    setThreads((prev) =>
      prev.map((t) => (t.id === thread.id ? { ...t, status: "closed" as const, isRead: true, snoozedUntil: null } : t))
    );
    const ok = await markThreadDone(caseId);
    if (ok) {
      showToast(`Thread ${thread.senderName} marked as done.`);
    } else {
      setThreads((prev) => prev.map((t) => (t.id === thread.id ? { ...t, status: prevStatus } : t)));
      showToast(`Could not mark ${thread.senderName} as done.`);
    }
  };

  const handleSnoozeThread = async (thread: InboxThread) => {
    const caseId = thread.caseId || thread.id;
    const prevSnooze = thread.snoozedUntil ?? null;
    const tomorrowIso = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
    setThreads((prev) =>
      prev.map((t) => (t.id === thread.id ? { ...t, snoozedUntil: tomorrowIso, isRead: true } : t))
    );
    const res = await snoozeThread(caseId);
    if (res.ok) {
      if (res.snoozedUntil) {
        setThreads((prev) =>
          prev.map((t) => (t.id === thread.id ? { ...t, snoozedUntil: res.snoozedUntil, isRead: true } : t))
        );
      }
      showToast(`Thread ${thread.senderName} snoozed until tomorrow.`);
    } else {
      setThreads((prev) => prev.map((t) => (t.id === thread.id ? { ...t, snoozedUntil: prevSnooze } : t)));
      showToast(`Could not snooze ${thread.senderName}.`);
    }
  };

  const toThreadRowItem = (thread: InboxThread): ThreadRowItem => ({
    id: thread.id,
    contactName: thread.senderName,
    channel: thread.channel,
    unit: thread.unitLabel,
    subject: thread.subject || thread.issueTitle || thread.caseRef,
    snippet: thread.latestSnippet,
    hasDraft: Boolean(
      thread.draftProposal?.drafts?.length ||
      thread.draftProposal?.whatsappDrafts?.length ||
      thread.draftProposal?.gmailDrafts?.length
    ),
    lastAt: thread.receivedAt,
    urgent: isUrgent(thread),
    isRead: thread.isRead,
    roleLabel: thread.recipientRoleDetail,
    category: thread.category,
    status: "needs_you",
    count: thread.messages?.length || 1,
  });

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
  ], [currentNeedsYouCount, currentUrgentCount, metrics.autonomousActionsWeek, t]);

  // Today Date & Greeting - Defer evaluation to client mount to prevent Next.js prerender error
  const [todayFormatted, setTodayFormatted] = useState<string>("");

  useEffect(() => {
    setTodayFormatted(formatLongDay(new Date()));
  }, []);

  // Lead rows with dynamic slicing (no fabricated default leads)
  const leadItems: ProspectiveInquiry[] = useMemo(() => {
    const limit = activeSection === "all" ? 3 : 50;
    return inquiries.slice(0, limit);
  }, [inquiries, activeSection]);

  // Open rent by days overdue, from the tenants' own overdue rent. Empty until rent payments are mirrored.
  const overdueTenants = (tenants ?? []).filter((t) => t.rentStatus === "overdue" && t.overdueDays > 0 && (t.monthlyRentEur ?? 0) > 0);
  const agingTotal = overdueTenants.reduce((sum, t) => sum + (t.monthlyRentEur ?? 0), 0);
  const agingBuckets = [
    { label: "1–30 days", min: 1, max: 30, barClass: "bg-[var(--ink)]" },
    { label: "31–90 days", min: 31, max: 90, barClass: "bg-[var(--ink-3)]" },
    { label: "91+ days", min: 91, max: Infinity, barClass: "bg-[var(--accent)]" },
  ].map((bucket) => {
    const sum = overdueTenants.filter((t) => t.overdueDays >= bucket.min && t.overdueDays <= bucket.max).reduce((n, t) => n + (t.monthlyRentEur ?? 0), 0);
    return { ...bucket, sum, amount: formatCurrency(sum), pct: agingTotal > 0 ? (sum / agingTotal) * 100 : 0 };
  });

  // Occupancy per building and overall: the same portfolio data the Properties page shows
  const occupancyBuildings = (portfolio ?? []).map((c) => ({
    name: c.name,
    rate: c.occupancyRate,
    occupied: c.occupiedUnits,
    total: c.totalUnits,
  }));
  const portfolioUnits = occupancyBuildings.reduce((n, b) => n + b.total, 0);
  const portfolioOccupied = occupancyBuildings.reduce((n, b) => n + b.occupied, 0);
  const occupancyHeadline =
    portfolio && portfolioUnits > 0 ? `${Math.round((portfolioOccupied / portfolioUnits) * 1000) / 10}%` : "—";

  // Top buildings by vacancy first, then by largest total units
  const topOccupancyBuildings = [...occupancyBuildings]
    .sort((a, b) => {
      const aVacant = a.total - a.occupied;
      const bVacant = b.total - b.occupied;
      if (bVacant !== aVacant) return bVacant - aVacant;
      return b.total - a.total;
    })
    .slice(0, 4);
  const remainingBuildingsCount = Math.max(0, occupancyBuildings.length - topOccupancyBuildings.length);

  // Briefing mode: Daily pulse vs Weekly recap
  const [briefingKind, setBriefingKind] = useState<"daily" | "weekly">("daily");
  const { user } = useAuth();
  const firstName = user?.name?.trim().split(/\s+/)[0] ?? "";
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
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar pendingCount={currentNeedsYouCount} />

      {/* 2. Main Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar
          pageTitle="Main Dashboard"
        />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#162B45] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">
            <main className="flex-1 w-full max-w-[960px] mx-auto px-3.5 sm:px-6 lg:px-8 py-4 sm:py-8 pb-[calc(6.5rem+env(safe-area-inset-bottom))] md:pb-12 space-y-4 md:space-y-7 overflow-y-auto">

          {/* Top Briefing Header with Daily / Weekly Switcher */}
          <div className="space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 sm:gap-3">
              <div>
                <span className="text-[12px] sm:text-[13px] font-medium text-[var(--ink-3)] block tracking-tight">
                  {briefingKind === "daily" ? `${todayFormatted} · Amsterdam (CET)` : "9 Oct – 15 Oct (Weekly Review) · Amsterdam (CET)"}
                </span>
                <h1 className="font-heading font-bold text-[24px] sm:text-[32px] text-[var(--ink)] tracking-tight leading-none mt-1">
                  {briefingKind === "daily" ? "Hey" : "Weekly executive review"}{firstName ? `, ${firstName}` : ""}
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

            {/* Mobile-only: Compact 3-tile KPI strip so key counts sit cleanly at top */}
            <div className="grid grid-cols-3 gap-2 md:hidden pt-0.5">
              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "needs_you" ? "all" : "needs_you")}
                className={cn(
                  "rounded-xl border px-3 py-2 text-left transition-colors cursor-pointer",
                  activeSection === "needs_you"
                    ? "bg-[var(--ink)] border-[var(--ink)] text-white"
                    : "bg-[var(--bg)]/70 border-[var(--line)] text-[var(--ink)]"
                )}
              >
                <div className="text-[18px] font-bold tabular-nums leading-tight">
                  {currentNeedsYouCount}
                </div>
                <div
                  className={cn(
                    "text-[11px] font-medium truncate",
                    activeSection === "needs_you" ? "text-white/80" : "text-[var(--ink-3)]"
                  )}
                >
                  {t("need you")}
                </div>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "urgent" ? "all" : "urgent")}
                className={cn(
                  "rounded-xl border px-3 py-2 text-left transition-colors cursor-pointer",
                  activeSection === "urgent"
                    ? "bg-[var(--ink)] border-[var(--ink)] text-white"
                    : currentUrgentCount > 0
                    ? "bg-[var(--accent)]/8 border-[var(--accent)]/25 text-[var(--accent-ink)]"
                    : "bg-[var(--bg)]/70 border-[var(--line)] text-[var(--ink)]"
                )}
              >
                <div className="text-[18px] font-bold tabular-nums leading-tight flex items-center gap-1.5">
                  <span>{currentUrgentCount}</span>
                  {currentUrgentCount > 0 && activeSection !== "urgent" && (
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent)]" />
                  )}
                </div>
                <div
                  className={cn(
                    "text-[11px] font-medium truncate",
                    activeSection === "urgent"
                      ? "text-white/80"
                      : currentUrgentCount > 0
                      ? "text-[var(--accent-ink)]"
                      : "text-[var(--ink-3)]"
                  )}
                >
                  {t("urgent")}
                </div>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "overview" ? "all" : "overview")}
                className={cn(
                  "rounded-xl border px-3 py-2 text-left transition-colors cursor-pointer",
                  activeSection === "overview"
                    ? "bg-[var(--ink)] border-[var(--ink)] text-white"
                    : "bg-[var(--bg)]/70 border-[var(--line)] text-[var(--ink)]"
                )}
              >
                <div className="text-[18px] font-bold tabular-nums leading-tight">
                  {metrics.autonomousActionsWeek}
                </div>
                <div
                  className={cn(
                    "text-[11px] font-medium truncate",
                    activeSection === "overview" ? "text-white/80" : "text-[var(--ink-3)]"
                  )}
                >
                  {t("handled")}
                </div>
              </button>
            </div>

            {/* Mobile-only: Collapsible 2-line AI Briefing Card so urgent cards show immediately above the fold */}
            <div className="md:hidden rounded-xl border border-[var(--line)] bg-[var(--bg)]/50 p-3 space-y-2">
              <p
                className={cn(
                  "text-[13px] text-[var(--ink-2)] leading-relaxed",
                  !mobileBriefingTextExpanded && "line-clamp-2"
                )}
              >
                <span className="text-[var(--accent)] font-bold mr-1.5 select-none">✦</span>
                {briefingData?.summarySentence ? (
                  <span>{briefingData.summarySentence} </span>
                ) : briefingKind === "daily" ? (
                  <>Live triage queue: </>
                ) : (
                  <>Weekly portfolio summary: </>
                )}
                <Link
                  href="/inbox"
                  className="font-semibold text-[var(--ink)] underline underline-offset-4 whitespace-nowrap"
                >
                  {currentNeedsYouCount} need your call
                </Link>
                {currentUrgentCount > 0 ? (
                  <>
                    ,{" "}
                    <Link
                      href="/inbox"
                      className="font-semibold text-[var(--accent-ink)] underline underline-offset-4 whitespace-nowrap"
                    >
                      {currentUrgentCount} {currentUrgentCount === 1 ? "is" : "are"} urgent
                    </Link>
                  </>
                ) : null}
                .
              </p>

              <div className="flex items-center justify-between gap-2 pt-0.5">
                <button
                  type="button"
                  onClick={() => setMobileBriefingTextExpanded((prev) => !prev)}
                  className="text-[11.5px] font-semibold text-[var(--accent-ink)] hover:underline cursor-pointer"
                >
                  {mobileBriefingTextExpanded ? "Show less" : "Read full briefing"}
                </button>

                {briefingData?.sections && briefingData.sections.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setIsBriefingExpanded((prev) => !prev)}
                    className="text-[11.5px] font-semibold text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center gap-1 cursor-pointer py-0.5 px-2 rounded-md bg-white border border-[var(--line)]"
                  >
                    <span>{isBriefingExpanded ? "Hide breakdown" : "Breakdown"}</span>
                    <ChevronDown
                      className={cn(
                        "w-3 h-3 transition-transform duration-200",
                        isBriefingExpanded && "rotate-180"
                      )}
                    />
                  </button>
                )}
              </div>
            </div>

            {/* Desktop Sparkle Briefing Sentence with linked counts */}
            <div className="hidden md:flex sm:flex-row sm:items-start justify-between gap-3 pt-1">
              <p className="text-[14px] sm:text-[15px] text-[var(--ink-2)] leading-relaxed">
                <span className="text-[var(--accent)] font-bold mr-1.5 select-none">✦</span>
                {briefingData?.summarySentence ? (
                  <span>{briefingData.summarySentence} </span>
                ) : briefingKind === "daily" ? (
                  <>Live triage queue: </>
                ) : (
                  <>Weekly portfolio summary: </>
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

            {/* Desktop StatLine: Inline numbers separated by dividers, no boxes */}
            <div className="hidden md:block pt-1">
              <StatLine items={statLineItems} />
            </div>
          </div>

          {/* Section Navigation & Quick Filter Bar */}
          <div className="sticky top-0 md:top-2 z-20 -mx-3.5 sm:-mx-6 md:mx-0 md:my-2 px-3.5 sm:px-6 md:px-3 py-2 md:py-1.5 bg-white/95 md:bg-[var(--pane)]/95 backdrop-blur-md border-b md:border border-[var(--line)] rounded-none md:rounded-2xl md:shadow-xs flex items-center justify-between gap-3 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1.5 min-w-max">
              <button
                type="button"
                onClick={() => setActiveSection("all")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "all"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("All")}</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "urgent" ? "all" : "urgent")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "urgent"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                {currentUrgentCount > 0 && (
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full",
                      activeSection === "urgent" ? "bg-amber-300" : "bg-[var(--accent)]"
                    )}
                  />
                )}
                <span>{t("Urgent")}</span>
                {currentUrgentCount > 0 && (
                  <span
                    className={cn(
                      "font-mono text-[10.5px] px-1.5 py-0.2 rounded-full",
                      activeSection === "urgent"
                        ? "bg-white/20 text-white font-bold"
                        : "bg-[var(--accent)]/15 text-[var(--accent-ink)] font-semibold"
                    )}
                  >
                    {currentUrgentCount}
                  </span>
                )}
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "needs_you" ? "all" : "needs_you")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "needs_you"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("Needs you")}</span>
                <span
                  className={cn(
                    "font-mono text-[10.5px] px-1.5 py-0.2 rounded-full",
                    activeSection === "needs_you"
                      ? "bg-white/20 text-white font-bold"
                      : "bg-[var(--selected)] text-[var(--ink-2)] font-semibold"
                  )}
                >
                  {currentNeedsYouCount}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "waiting" ? "all" : "waiting")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "waiting"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("Waiting")}</span>
                <span
                  className={cn(
                    "font-mono text-[10.5px] px-1.5 py-0.2 rounded-full",
                    activeSection === "waiting"
                      ? "bg-white/20 text-white font-bold"
                      : "bg-[var(--selected)] text-[var(--ink-2)] font-semibold"
                  )}
                >
                  {radarItems.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "leads" ? "all" : "leads")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "leads"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("New leads")}</span>
                <span
                  className={cn(
                    "font-mono text-[10.5px] px-1.5 py-0.2 rounded-full",
                    activeSection === "leads"
                      ? "bg-white/20 text-white font-bold"
                      : "bg-[var(--selected)] text-[var(--ink-2)] font-semibold"
                  )}
                >
                  {leadItems.length}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "calendar" ? "all" : "calendar")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "calendar"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("Calendar")}</span>
              </button>

              <button
                type="button"
                onClick={() => setActiveSection(activeSection === "overview" ? "all" : "overview")}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5",
                  activeSection === "overview"
                    ? "bg-[var(--ink)] text-white font-semibold shadow-2xs"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--pane)] border border-transparent hover:border-[var(--line)]"
                )}
              >
                <span>{t("Overview")}</span>
              </button>
            </div>
          </div>

          {(activeSection === "all" || activeSection === "urgent") && (
            <BrixxAttentionCard
              items={attention.items}
              total={attention.total}
              urgentTotal={urgentAttentionCount}
              onlyUrgent={activeSection === "urgent"}
            />
          )}

          {/* Emergency Alert Card with In-Place Maintenance Ticket & Channel-Aware Actions */}
          {(activeSection === "all" || activeSection === "urgent") && (
            topUrgentThread ? (() => {
            const ticketNum = topUrgentThread.ticketNumber || ticketRef(topUrgentThread.caseId || topUrgentThread.id);
            const ticket: MaintenanceTicket = maintenanceTickets.find(
              (t) =>
                t.id === topUrgentThread.caseId ||
                t.id === topUrgentThread.id ||
                t.ticketNumber === ticketNum ||
                t.ticketNumber === `#${ticketNum.replace("#", "")}`
            ) || {
              ...DEFAULT_TICKET_TEMPLATE,
              ticketNumber: ticketNum,
              unitLabel: topUrgentThread.unitLabel || DEFAULT_TICKET_TEMPLATE.unitLabel,
              tenantName: topUrgentThread.senderName || DEFAULT_TICKET_TEMPLATE.tenantName,
              tenantPhone: topUrgentThread.senderContact || DEFAULT_TICKET_TEMPLATE.tenantPhone,
              issueTitle: topUrgentThread.subject || topUrgentThread.latestSnippet || DEFAULT_TICKET_TEMPLATE.issueTitle,
              originalMessage: topUrgentThread.latestSnippet || DEFAULT_TICKET_TEMPLATE.originalMessage,
            };

            const tenantChannel: "whatsapp" | "gmail" = topUrgentThread.channel === "gmail" ? "gmail" : "whatsapp";
            const emergencyKey = topUrgentThread.id || ticket.ticketNumber;
            const isTenantReplied = Boolean(tenantReplySentMap[emergencyKey]);
            const isContractorDispatched = Boolean(contractorDispatchedMap[emergencyKey]);

            return (
              <div
                id="section-emergency"
                className={cn(
                  "border-l-[4px] border-l-[var(--accent)] border-y border-r border-[var(--line)] bg-[var(--pane)] rounded-r-[var(--radius-pane)] transition-all overflow-hidden shadow-2xs"
                )}
              >
                {/* Mobile-only: Clean Compact Priority Card (collapses 2-screen inline wall into single scannable card) */}
                <div className="md:hidden p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className="inline-flex items-center px-2 py-0.5 rounded bg-[var(--accent)]/12 text-[var(--accent-ink)] font-bold text-[10.5px] uppercase tracking-wider shrink-0">
                        Emergency
                      </span>
                      {ticket.slaRemaining && (
                        <span className="font-mono text-[10.5px] text-[var(--accent-ink)] font-bold px-1.5 py-0.5 rounded bg-[var(--bg)] border border-[var(--line)] truncate">
                          {ticket.slaRemaining}
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => setMobileEmergencyOpen((prev) => !prev)}
                      className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--ink-2)] hover:text-[var(--ink)] py-0.5 px-2 rounded-md border border-[var(--line)] bg-[var(--bg)]/60 cursor-pointer shrink-0"
                      aria-expanded={mobileEmergencyOpen}
                    >
                      <span>{mobileEmergencyOpen ? t("Hide") : t("Review")}</span>
                      <ChevronDown
                        className={cn(
                          "w-3.5 h-3.5 transition-transform duration-200",
                          mobileEmergencyOpen && "rotate-180"
                        )}
                      />
                    </button>
                  </div>

                  <div
                    onClick={() => setMobileEmergencyOpen((prev) => !prev)}
                    className="space-y-1 cursor-pointer"
                  >
                    <div className="text-[14px] font-semibold text-[var(--ink)] leading-snug line-clamp-2">
                      {topUrgentThread.unitLabel}: {topUrgentThread.subject || topUrgentThread.latestSnippet}
                    </div>
                    <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--ink-3)] flex-wrap">
                      <span className="font-semibold text-[var(--ink-2)]">{ticket.tenantName}</span>
                      <span>·</span>
                      <span className="inline-flex items-center gap-1">
                        {tenantChannel === "whatsapp" ? (
                          <MessageSquare className="w-3 h-3 text-[#25D366]" />
                        ) : (
                          <Mail className="w-3 h-3 text-[#EA4335]" />
                        )}
                        {tenantChannel === "whatsapp" ? "WhatsApp" : "Email"}
                      </span>
                      <span>·</span>
                      <span className="font-mono">{topUrgentThread.relativeTime}</span>
                    </div>
                  </div>

                  {!mobileEmergencyOpen && (
                    <p className="text-[12.5px] text-[var(--ink-2)] italic line-clamp-2 pl-2.5 border-l-2 border-[var(--accent)]">
                      &ldquo;{topUrgentThread.latestSnippet || ticket.originalMessage}&rdquo;
                    </p>
                  )}

                  {/* Single aligned bottom action row */}
                  <div className="grid grid-cols-3 gap-1.5 pt-2 border-t border-[var(--line)]">
                    <button
                      type="button"
                      onClick={() => {
                        setActiveEditTicket(ticket);
                        setIsEditModalOpen(true);
                      }}
                      className="inline-flex items-center justify-center gap-1 px-2 py-1.5 text-[11.5px] font-semibold text-[var(--ink)] bg-[var(--bg)] hover:bg-[var(--selected)] border border-[var(--line)] rounded-lg cursor-pointer truncate"
                    >
                      <Ticket className="w-3.5 h-3.5 text-[var(--accent-ink)] shrink-0" />
                      <span className="truncate">{ticket.ticketNumber}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setMobileEmergencyOpen(true);
                        setMobileEmergencyTab("tenant");
                        handleSendTenantReply(ticket, tenantChannel, emergencyKey);
                      }}
                      className={cn(
                        "inline-flex items-center justify-center gap-1 px-2 py-1.5 text-[11.5px] font-semibold rounded-lg border cursor-pointer truncate",
                        isTenantReplied
                          ? "bg-[var(--bg)] text-[var(--ink)] border-[var(--line)]"
                          : "bg-white hover:bg-[var(--selected)] text-[var(--ink)] border-[var(--line)]"
                      )}
                    >
                      {tenantChannel === "whatsapp" ? (
                        <MessageSquare className="w-3.5 h-3.5 text-[#25D366] shrink-0" />
                      ) : (
                        <Mail className="w-3.5 h-3.5 text-[#EA4335] shrink-0" />
                      )}
                      <span className="truncate">{isTenantReplied ? t("Replied") : t("Reply")}</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setMobileEmergencyOpen(true);
                        setMobileEmergencyTab("contractor");
                        handleDispatchContractor(ticket, emergencyKey);
                      }}
                      disabled={isContractorDispatched}
                      className={cn(
                        "inline-flex items-center justify-center gap-1 px-2 py-1.5 text-[11.5px] font-semibold rounded-lg cursor-pointer truncate",
                        isContractorDispatched
                          ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)]"
                          : "bg-[var(--ink)] hover:bg-[var(--ink)]/90 text-white"
                      )}
                    >
                      <Wrench className="w-3.5 h-3.5 text-[var(--accent)] shrink-0" />
                      <span className="truncate">{isContractorDispatched ? t("Sent") : t("Dispatch")}</span>
                    </button>
                  </div>

                  {/* Mobile Expanded View: Compact quote + Tabbed Drafts (1 at a time) */}
                  {mobileEmergencyOpen && (
                    <div className="pt-2.5 border-t border-[var(--line)] space-y-3 animate-in fade-in duration-150">
                      <div className="rounded-lg bg-[var(--bg)]/60 border border-[var(--line)] p-3 space-y-1">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--ink-3)] block">
                          Tenant Message ({topUrgentThread.senderContact || ticket.tenantPhone})
                        </span>
                        <p className="text-[13px] text-[var(--ink)] italic leading-relaxed pl-2.5 border-l-2 border-[var(--accent)]">
                          &ldquo;{topUrgentThread.latestSnippet || ticket.originalMessage}&rdquo;
                        </p>
                      </div>

                      {/* Segmented Draft Tabs instead of stacking two giant textareas */}
                      <div className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-[var(--bg)] border border-[var(--line)]">
                        <button
                          type="button"
                          onClick={() => setMobileEmergencyTab("tenant")}
                          className={cn(
                            "py-1.5 px-2 rounded-lg text-[11.5px] font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer",
                            mobileEmergencyTab === "tenant"
                              ? "bg-white text-[var(--ink)] shadow-2xs border border-[var(--line)]"
                              : "text-[var(--ink-3)]"
                          )}
                        >
                          {tenantChannel === "whatsapp" ? (
                            <MessageSquare className="w-3.5 h-3.5 text-[#25D366]" />
                          ) : (
                            <Mail className="w-3.5 h-3.5 text-[#EA4335]" />
                          )}
                          <span>Tenant Reply</span>
                          {isTenantReplied && <Check className="w-3 h-3 text-emerald-600" />}
                        </button>
                        <button
                          type="button"
                          onClick={() => setMobileEmergencyTab("contractor")}
                          className={cn(
                            "py-1.5 px-2 rounded-lg text-[11.5px] font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer",
                            mobileEmergencyTab === "contractor"
                              ? "bg-white text-[var(--ink)] shadow-2xs border border-[var(--line)]"
                              : "text-[var(--ink-3)]"
                          )}
                        >
                          <Wrench className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                          <span>Work Order</span>
                          {isContractorDispatched && <Check className="w-3 h-3 text-emerald-600" />}
                        </button>
                      </div>

                      {mobileEmergencyTab === "tenant" ? (
                        <div className="space-y-2.5">
                          <textarea
                            rows={4}
                            value={
                              customTenantReplyText[ticket.ticketNumber] ??
                              (ticket.tenantDraft?.trim() ? ticket.tenantDraft : undefined) ??
                              (tenantChannel === "whatsapp"
                                ? topUrgentThread.draftProposal?.whatsappDrafts?.[0]?.text
                                : topUrgentThread.draftProposal?.gmailDrafts?.[0]?.text) ??
                              topUrgentThread.draftProposal?.drafts?.[0]?.text ??
                              ""
                            }
                            onChange={(e) =>
                              setCustomTenantReplyText((prev) => ({
                                ...prev,
                                [ticket.ticketNumber]: e.target.value,
                              }))
                            }
                            disabled={isTenantReplied}
                            className="w-full min-h-[104px] text-[13px] p-2.5 rounded-lg border border-[var(--line)] bg-[var(--bg)] focus:bg-white focus:outline-hidden focus:border-[var(--accent)] leading-relaxed text-[var(--ink)]"
                            placeholder="Type reply to tenant..."
                          />
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] text-[var(--ink-3)] truncate">
                              To: {ticket.tenantName}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleSendTenantReply(ticket, tenantChannel, emergencyKey)}
                              disabled={isTenantReplied}
                              className={cn(
                                "px-3.5 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 shrink-0 cursor-pointer",
                                isTenantReplied
                                  ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)] cursor-default"
                                  : "bg-[var(--ink)] text-white"
                              )}
                            >
                              {isTenantReplied ? (
                                <>
                                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                                  <span>Sent</span>
                                </>
                              ) : (
                                <>
                                  <Send className="w-3.5 h-3.5 text-[var(--accent)]" />
                                  <span>Send to Tenant</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="space-y-2.5">
                          <textarea
                            rows={4}
                            value={customContractorText[ticket.ticketNumber] ?? ticket.contractorDraft ?? ""}
                            onChange={(e) =>
                              setCustomContractorText((prev) => ({
                                ...prev,
                                [ticket.ticketNumber]: e.target.value,
                              }))
                            }
                            disabled={isContractorDispatched}
                            className="w-full min-h-[104px] text-[13px] p-2.5 rounded-lg border border-[var(--line)] bg-[var(--bg)] focus:bg-white focus:outline-hidden focus:border-[var(--accent)] leading-relaxed text-[var(--ink)]"
                            placeholder="Contractor work order details..."
                          />
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[11px] text-[var(--ink-3)] truncate">
                              {ticket.contractorName} · {ticket.poBudgetCap ? `Cap: ${ticket.poBudgetCap}` : "No cap"}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleDispatchContractor(ticket, emergencyKey)}
                              disabled={isContractorDispatched}
                              className={cn(
                                "px-3.5 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 shrink-0 cursor-pointer",
                                isContractorDispatched
                                  ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)] cursor-default"
                                  : "bg-[var(--ink)] text-white"
                              )}
                            >
                              {isContractorDispatched ? (
                                <>
                                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                                  <span>Dispatched</span>
                                </>
                              ) : (
                                <>
                                  <Wrench className="w-3.5 h-3.5 text-[var(--accent)]" />
                                  <span>Dispatch Work Order</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      )}

                      <div className="pt-2 border-t border-[var(--line)] flex justify-end">
                        <button
                          type="button"
                          onClick={() => {
                            setActiveEditTicket(ticket);
                            setIsEditModalOpen(true);
                          }}
                          className="px-3 py-1.5 rounded-lg border border-[var(--line)] text-xs font-semibold text-[var(--ink)] hover:bg-[var(--selected)] inline-flex items-center gap-1.5 cursor-pointer"
                        >
                          <Pencil className="w-3 h-3 text-[var(--accent-ink)]" />
                          <span>Edit Ticket Details</span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Desktop Prominent Header Bar */}
                <div className="hidden md:flex p-4 sm:px-5 sm:py-3.5 flex-row items-center justify-between gap-3">
                  <div className="flex items-start sm:items-center gap-2.5 min-w-0">
                    <span className="font-bold text-[13px] text-[var(--accent-ink)] uppercase tracking-wider shrink-0 mt-0.5 sm:mt-0">
                      Emergency
                    </span>
                    <span className="text-[var(--line)] hidden sm:inline">·</span>
                    <div className="min-w-0 truncate">
                      <span className="text-[14.5px] font-semibold text-[var(--ink)]">
                        {topUrgentThread.unitLabel}:
                      </span>{" "}
                      <span className="text-[13.5px] text-[var(--ink-2)] font-medium">
                        {topUrgentThread.subject || topUrgentThread.latestSnippet}
                      </span>
                    </div>
                  </div>

                  {/* Exactly Required Options: In-Place Details, Channel-Specific Tenant Reply, Contractor Dispatch */}
                  <div className="flex items-center gap-2 shrink-0 self-end md:self-center flex-wrap">
                    {ticket.slaRemaining && (
                      <span className="font-mono text-xs text-[var(--accent-ink)] font-bold px-2 py-0.5 rounded bg-[var(--accent)]/10 border border-[var(--accent)]/20">
                        {ticket.slaRemaining}
                      </span>
                    )}

                    {/* View Ticket Details on the same page */}
                    <button
                      type="button"
                      onClick={() => {
                        setActiveEditTicket(ticket);
                        setIsEditModalOpen(true);
                      }}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-[var(--ink)] bg-[var(--bg)] hover:bg-[var(--selected)] border border-[var(--line)] rounded-lg transition-colors cursor-pointer"
                      title="View and Edit Maintenance Ticket on this page"
                    >
                      <Ticket className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                      <span>{ticket.ticketNumber} {t("Details")}</span>
                    </button>

                    {/* Expand/Collapse In-Place Card */}
                    <button
                      type="button"
                      onClick={() => setIsEmergencyExpanded(!isEmergencyExpanded)}
                      className="text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center gap-1 cursor-pointer py-1 px-1.5 rounded hover:bg-[var(--selected)]"
                      aria-expanded={isEmergencyExpanded}
                      title="Toggle in-place ticket context"
                    >
                      <span>{isEmergencyExpanded ? t("Hide") : t("Details")}</span>
                      <ChevronDown
                        className={cn(
                          "w-3.5 h-3.5 transition-transform duration-200",
                          isEmergencyExpanded && "rotate-180"
                        )}
                      />
                    </button>

                    <span className="text-[var(--line)]">|</span>

                    {/* Option 1: Reply to Tenant (Strictly matched to message channel: WhatsApp vs Gmail) */}
                    <button
                      type="button"
                      onClick={() => {
                        setIsEmergencyExpanded(true);
                        handleSendTenantReply(ticket, tenantChannel, emergencyKey);
                      }}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-lg border transition-all cursor-pointer shadow-2xs",
                        isTenantReplied
                          ? "bg-[var(--bg)] text-[var(--ink-2)] border-[var(--line)]"
                          : "bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink)] border-[var(--line)]"
                      )}
                      title={`Send reply to tenant via ${tenantChannel === "whatsapp" ? "WhatsApp" : "Email"}`}
                    >
                      {tenantChannel === "whatsapp" ? (
                        <MessageSquare className="w-3.5 h-3.5 text-[#25D366]" />
                      ) : (
                        <Mail className="w-3.5 h-3.5 text-[#EA4335]" />
                      )}
                      <span>
                        {isTenantReplied
                          ? `${t("Replied")} (${tenantChannel === "whatsapp" ? "WhatsApp" : "Email"})`
                          : `${t("Reply Tenant")} (${tenantChannel === "whatsapp" ? "WhatsApp" : "Email"})`}
                      </span>
                    </button>

                    {/* Option 2: Dispatch Ticket to Contractor */}
                    <button
                      type="button"
                      onClick={() => {
                        setIsEmergencyExpanded(true);
                        handleDispatchContractor(ticket, emergencyKey);
                      }}
                      disabled={isContractorDispatched}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-3 py-1 text-xs font-semibold rounded-lg transition-all cursor-pointer shadow-2xs",
                        isContractorDispatched
                          ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)]"
                          : "bg-[var(--ink)] hover:bg-[var(--ink)]/90 text-white"
                      )}
                      title="Approve work order and dispatch ticket to contractor"
                    >
                      <Wrench className="w-3.5 h-3.5 text-[var(--accent)]" />
                      <span>
                        {isContractorDispatched
                          ? t("Contractor Dispatched")
                          : `${t("Dispatch to")} ${ticket.contractorName || t("Contractor")}`}
                      </span>
                    </button>
                  </div>
                </div>

                {/* Prominent Details Section: In-Place Context & Full Ticket on Same Page (Desktop) */}
                {isEmergencyExpanded && (
                  <div className="hidden md:block border-t border-[var(--line)] bg-[var(--bg)]/50 px-5 sm:px-6 py-5 space-y-5 animate-in fade-in duration-150">
                    {/* Inbound Distress Message with Clear Channel Badge */}
                    <div className="bg-[var(--pane)] rounded-xl border border-[var(--line)] p-4 sm:p-5 shadow-xs space-y-3">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--line)] pb-2.5">
                        <div className="flex items-center gap-2 flex-wrap">
                          {tenantChannel === "whatsapp" ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--bg)] text-[var(--ink)] font-semibold text-xs border border-[var(--line)]">
                              <MessageSquare className="w-3.5 h-3.5 text-[#25D366]" />
                              <span>Inbound via WhatsApp · {topUrgentThread.senderContact || ticket.tenantPhone}</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--bg)] text-[var(--ink)] font-semibold text-xs border border-[var(--line)]">
                              <Mail className="w-3.5 h-3.5 text-[#EA4335]" />
                              <span>Inbound via Email · {topUrgentThread.senderContact}</span>
                            </span>
                          )}
                          <span className="text-[var(--ink-3)] hidden sm:inline">·</span>
                          <span className="text-[13px] font-bold text-[var(--ink)]">{ticket.tenantName}</span>
                          <span className="text-xs text-[var(--ink-3)] font-mono">({ticket.unitLabel})</span>
                        </div>
                        <span className="font-mono text-xs font-semibold text-[var(--ink-3)] bg-[var(--selected)] px-2.5 py-0.5 rounded border border-[var(--line)]">
                          {topUrgentThread.relativeTime}
                        </span>
                      </div>

                      {/* Prominent, readable distress message - No scrolling required */}
                      <div className="py-1">
                        <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)] block mb-1.5">
                          Tenant Distress Message:
                        </span>
                        <p className="text-[15px] sm:text-[16px] text-[var(--ink)] italic font-normal leading-relaxed pl-4 border-l-4 border-[var(--accent)] select-text bg-[var(--bg)]/40 py-3 rounded-r-lg">
                          "{topUrgentThread.latestSnippet || ticket.originalMessage}"
                        </p>
                      </div>
                    </div>

                    {/* Staged Action Cards: Reply to Tenant vs Work Order to Contractor */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
                      {/* Card 1: Reply to Tenant (same channel) */}
                      <div className="bg-[var(--pane)] rounded-xl border border-[var(--line)] p-4 sm:p-5 flex flex-col justify-between space-y-3.5 shadow-2xs">
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-bold uppercase tracking-wider text-[var(--ink)] flex items-center gap-2">
                              {tenantChannel === "whatsapp" ? (
                                <MessageSquare className="w-4 h-4 text-[#25D366]" />
                              ) : (
                                <Mail className="w-4 h-4 text-[#EA4335]" />
                              )}
                              <span>1. Outgoing Tenant Reply ({tenantChannel === "whatsapp" ? "WhatsApp" : "Email"})</span>
                            </span>
                            <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)]">
                              <span
                                className={cn(
                                  "w-1.5 h-1.5 rounded-full",
                                  isTenantReplied ? "bg-emerald-500" : "bg-amber-500"
                                )}
                              />
                              <span>{isTenantReplied ? "Message Sent" : "Ready to Send"}</span>
                            </span>
                          </div>
                          {/* Expanded 6-row textarea with min-h-[145px] so full message is visible without scrolling */}
                          <textarea
                            rows={6}
                            value={
                              customTenantReplyText[ticket.ticketNumber] ??
                              (ticket.tenantDraft?.trim() ? ticket.tenantDraft : undefined) ??
                              (tenantChannel === "whatsapp"
                                ? topUrgentThread.draftProposal?.whatsappDrafts?.[0]?.text
                                : topUrgentThread.draftProposal?.gmailDrafts?.[0]?.text) ??
                              topUrgentThread.draftProposal?.drafts?.[0]?.text ??
                              ""
                            }
                            onChange={(e) =>
                              setCustomTenantReplyText((prev) => ({
                                ...prev,
                                [ticket.ticketNumber]: e.target.value,
                              }))
                            }
                            disabled={isTenantReplied}
                            className="w-full min-h-[145px] text-[13.5px] p-3 rounded-lg border border-[var(--line)] bg-[var(--bg)] focus:bg-[var(--pane)] focus:outline-hidden focus:border-[var(--accent)] transition-colors leading-relaxed text-[var(--ink)] font-normal resize-y"
                            placeholder="Type reply to tenant..."
                          />
                        </div>

                        <div className="flex items-center justify-between pt-1">
                          <span className="text-xs text-[var(--ink-3)] font-medium">
                            To: {ticket.tenantName} ({topUrgentThread.senderContact || ticket.tenantPhone})
                          </span>
                          <button
                            type="button"
                            onClick={() => handleSendTenantReply(ticket, tenantChannel, emergencyKey)}
                            disabled={isTenantReplied}
                            className={cn(
                              "min-w-[175px] justify-center px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 shadow-2xs",
                              isTenantReplied
                                ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)] cursor-default"
                                : "bg-[var(--ink)] text-white hover:bg-[var(--ink)]/90"
                            )}
                          >
                            {isTenantReplied ? (
                              <>
                                <Check className="w-3.5 h-3.5 text-emerald-600" />
                                <span>Sent via {tenantChannel === "whatsapp" ? "WhatsApp" : "Email"}</span>
                              </>
                            ) : (
                              <>
                                <Send className="w-3.5 h-3.5 text-[var(--accent)]" />
                                <span>Send to Tenant</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>

                      {/* Card 2: Work Order to Contractor */}
                      <div className="bg-[var(--pane)] rounded-xl border border-[var(--line)] p-4 sm:p-5 flex flex-col justify-between space-y-3.5 shadow-2xs">
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-bold uppercase tracking-wider text-[var(--ink)] flex items-center gap-2">
                              <Wrench className="w-4 h-4 text-[var(--accent-ink)]" />
                              <span>2. Work Order ({ticket.contractorName})</span>
                            </span>
                            {(() => {
                              const isUnavailable = (ticket as any).status === "contractor_unavailable" || (ticket as any).contractorStatus === "unavailable";
                              return (
                                <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)]">
                                  <span
                                    className={cn(
                                      "w-1.5 h-1.5 rounded-full",
                                      isUnavailable
                                        ? "bg-rose-500"
                                        : isContractorDispatched
                                        ? "bg-emerald-500"
                                        : "bg-[var(--accent)]"
                                    )}
                                  />
                                  <span>
                                    {isUnavailable
                                      ? "Contractor Unavailable"
                                      : isContractorDispatched
                                      ? "Dispatched"
                                      : ticket.poBudgetCap
                                      ? `Cap: ${ticket.poBudgetCap}`
                                      : "No cap recorded"}
                                  </span>
                                </span>
                              );
                            })()}
                          </div>
                          {/* Expanded 6-row textarea with min-h-[145px] so full work order is visible without scrolling */}
                          <textarea
                            rows={6}
                            value={customContractorText[ticket.ticketNumber] ?? ticket.contractorDraft ?? ""}
                            onChange={(e) =>
                              setCustomContractorText((prev) => ({
                                ...prev,
                                [ticket.ticketNumber]: e.target.value,
                              }))
                            }
                            disabled={isContractorDispatched}
                            className="w-full min-h-[145px] text-[13.5px] p-3 rounded-lg border border-[var(--line)] bg-[var(--bg)] focus:bg-[var(--pane)] focus:outline-hidden focus:border-[var(--accent)] transition-colors leading-relaxed text-[var(--ink)] font-normal resize-y"
                            placeholder="Contractor work order details..."
                          />
                        </div>

                        <div className="flex items-center justify-between pt-1">
                          <span className="text-xs text-[var(--ink-3)] font-medium">
                            {ticket.contractorTrade} · Key lockbox #4182
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDispatchContractor(ticket, emergencyKey)}
                            disabled={isContractorDispatched}
                            className={cn(
                              "min-w-[175px] justify-center px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 shadow-2xs",
                              isContractorDispatched
                                ? "bg-[var(--bg)] text-[var(--ink)] border border-[var(--line)] cursor-default"
                                : "bg-[var(--ink)] text-white hover:bg-[var(--ink)]/90"
                            )}
                          >
                            {isContractorDispatched ? (
                              <>
                                <Check className="w-3.5 h-3.5 text-emerald-600" />
                                <span>Dispatched</span>
                              </>
                            ) : (
                              <>
                                <Wrench className="w-3.5 h-3.5 text-[var(--accent)]" />
                                <span>Dispatch Work Order</span>
                              </>
                            )}
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* Prominent Quick In-Place Action Bar */}
                    <div className="pt-3 pb-1 border-t border-[var(--line)] flex flex-wrap items-center justify-between gap-3">
                      <div className="text-[13px] text-[var(--ink-2)] font-medium">
                        {isContractorDispatched && isTenantReplied ? (
                          <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-600">
                            <Check className="w-4 h-4" />
                            <span>Ticket {ticket.ticketNumber} fully approved & dispatched to contractor and tenant.</span>
                          </span>
                        ) : (
                          <span>Review the two drafts above to send directly to tenant and dispatch to contractor.</span>
                        )}
                      </div>

                      <div className="flex items-center gap-2.5">
                        <button
                          type="button"
                          onClick={() => {
                            setActiveEditTicket(ticket);
                            setIsEditModalOpen(true);
                          }}
                          className="px-3.5 py-2 rounded-lg border border-[var(--line)] text-xs font-semibold text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer inline-flex items-center gap-1.5"
                        >
                          <Pencil className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                          <span>Edit Ticket Details</span>
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
            })() : (
              activeSection === "urgent" ? (
                <div className="p-8 text-center bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] space-y-2">
                  <ShieldCheck className="w-6 h-6 text-emerald-600 mx-auto" />
                  <p className="text-sm font-semibold text-[var(--ink)]">No urgent issues</p>
                  <p className="text-xs text-[var(--ink-3)]">All critical tickets and SLAs are within normal parameters.</p>
                </div>
              ) : null
            )
          )}

          {/* Additional urgent messages rendered as compact rows (Top 3 + View more, like Needs You) */}
          {(activeSection === "all" || activeSection === "urgent") && otherUrgentThreads.length > 0 && (() => {
            const urgentLimit = activeSection === "urgent" || showAllUrgent ? 50 : 3;
            const visibleUrgent = otherUrgentThreads.slice(0, urgentLimit);
            const hiddenUrgentCount = Math.max(0, otherUrgentThreads.length - visibleUrgent.length);
            return (
            <section id="section-urgent-list" className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
              <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
                <SectionHeader
                  title={t("Other urgent messages")}
                  count={otherUrgentThreads.length}
                  actionText={t("Open Inbox →")}
                  actionHref="/inbox?tab=needs_you"
                />
              </div>
              <div className="divide-y divide-[var(--line)]">
                {visibleUrgent.map((thread) => (
                  <ThreadRow
                    key={thread.id}
                    t={toThreadRowItem(thread)}
                    onSelect={() => router.push(`/inbox?thread=${thread.id}`)}
                    onDone={() => handleDoneThread(thread)}
                    onSnooze={() => handleSnoozeThread(thread)}
                  />
                ))}
              </div>
              {(hiddenUrgentCount > 0 || (showAllUrgent && otherUrgentThreads.length > 3 && activeSection === "all")) && (
                <div className="px-4 sm:px-5 py-2.5 border-t border-[var(--line)] bg-[var(--bg)]/50 flex items-center justify-between text-xs">
                  <button
                    type="button"
                    onClick={() => setShowAllUrgent((prev) => !prev)}
                    className="font-semibold text-[var(--ink)] hover:underline cursor-pointer"
                  >
                    {showAllUrgent
                      ? t("Show fewer")
                      : `${t("View more")} (+${hiddenUrgentCount})`}
                  </button>
                  <Link href="/inbox?tab=needs_you" className="font-medium text-[var(--accent-ink)] hover:underline">
                    {t("Open Inbox →")}
                  </Link>
                </div>
              )}
            </section>
            );
          })()}

          {/* Section 1: Needs You (Top 3 priority-sorted threads + View more + real Done/Snooze) */}
          {(activeSection === "all" || activeSection === "needs_you") && (() => {
            const visibleLimit = activeSection === "needs_you" || showAllNeedsYou ? 50 : 3;
            const visibleNeedsYou = needsYouThreads.slice(0, visibleLimit);
            const hiddenCount = Math.max(0, needsYouThreads.length - visibleNeedsYou.length);
            return (
          <section id="section-needs-you" className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title={t("Needs you")}
                count={needsYouThreads.length}
                actionText={t("Open Inbox →")}
                actionHref="/inbox"
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {needsYouThreads.length > 0 ? (
                visibleNeedsYou.map((thread) => {
                  const isMaintenance = thread.category === "maintenance" && thread.recipientRole !== "contractor";

                  return (
                    <div key={thread.id} className="group">
                      <ThreadRow
                        t={toThreadRowItem(thread)}
                        onSelect={() => router.push(`/inbox?thread=${thread.id}`)}
                        onDone={() => handleDoneThread(thread)}
                        onSnooze={() => handleSnoozeThread(thread)}
                      />
                      {/* For maintenance messages: strictly isolated by thread ID (thread.id) */}
                      {isMaintenance && (() => {
                        const mTicket = maintenanceTickets.find(
                          (mt) =>
                            mt.id === thread.caseId ||
                            mt.id === thread.id ||
                            mt.ticketNumber === thread.ticketNumber ||
                            mt.ticketNumber === `#${thread.ticketNumber?.replace('#', '')}`
                        ) || {
                          ...DEFAULT_TICKET_TEMPLATE,
                          id: `m-${thread.id}`,
                          ticketNumber: thread.ticketNumber || `#0${thread.id.replace(/\D/g, '').slice(-2) || '15'}`,
                          unitLabel: thread.unitLabel || DEFAULT_TICKET_TEMPLATE.unitLabel,
                          tenantName: thread.senderName || DEFAULT_TICKET_TEMPLATE.tenantName,
                          tenantPhone: thread.senderContact || DEFAULT_TICKET_TEMPLATE.tenantPhone,
                          issueTitle: thread.subject || thread.latestSnippet || DEFAULT_TICKET_TEMPLATE.issueTitle,
                        };

                        const tChannel = thread.channel === "gmail" ? "gmail" : "whatsapp";
                        const isReplied = Boolean(tenantReplySentMap[thread.id]);
                        const isDispatched = Boolean(contractorDispatchedMap[thread.id]);
                        const hasContractorContact = Boolean(
                          mTicket.contractorPhone?.trim() || mTicket.contractorEmail?.trim()
                        );

                        return (
                          <div className="bg-[var(--bg)]/50 border-b border-[var(--line)] px-4 py-2 flex flex-wrap items-center justify-between gap-2 text-xs">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] px-2 py-0.5 rounded border border-[var(--line)]">
                                {mTicket.ticketNumber} Maintenance
                              </span>
                              <span className="text-[var(--ink-3)] hidden sm:inline truncate max-w-xs">
                                {mTicket.poBudgetCap ? `Cap: ${mTicket.poBudgetCap} · ` : ""}
                                {mTicket.contractorName || t("No contractor assigned")}
                              </span>
                            </div>

                            <div className="grid grid-cols-3 gap-1.5 w-full md:w-auto md:flex md:items-center md:gap-2">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setActiveEditTicket(mTicket);
                                  setIsEditModalOpen(true);
                                }}
                                className="inline-flex items-center justify-center gap-1 px-2 md:px-2.5 py-1.5 md:py-1 rounded-lg md:rounded bg-[var(--pane)] hover:bg-[var(--selected)] border border-[var(--line)] text-[11.5px] md:text-xs font-medium text-[var(--ink)] transition-colors cursor-pointer truncate"
                                title="View/Edit ticket details on this page"
                              >
                                <Ticket className="w-3 h-3 text-[var(--accent-ink)] shrink-0" />
                                <span className="truncate">{t("Ticket Details")}</span>
                              </button>

                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSendTenantReply(mTicket, tChannel, thread.id);
                                }}
                                className={cn(
                                  "inline-flex items-center justify-center gap-1 px-2 md:px-2.5 py-1.5 md:py-1 rounded-lg md:rounded border text-[11.5px] md:text-xs font-semibold transition-colors cursor-pointer truncate",
                                  isReplied
                                    ? "bg-[var(--bg)] text-[var(--ink-2)] border-[var(--line)]"
                                    : "bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink)] border-[var(--line)]"
                                )}
                              >
                                {tChannel === "whatsapp" ? (
                                  <MessageSquare className="w-3 h-3 text-[#25D366] shrink-0" />
                                ) : (
                                  <Mail className="w-3 h-3 text-[#EA4335] shrink-0" />
                                )}
                                <span className="truncate md:hidden">{isReplied ? t("Replied") : t("Reply")}</span>
                                <span className="hidden md:inline">{isReplied ? t("Replied") : `${t("Reply")} (${tChannel === "whatsapp" ? "WhatsApp" : "Email"})`}</span>
                              </button>

                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (!hasContractorContact) {
                                    setActiveEditTicket(mTicket);
                                    setIsEditModalOpen(true);
                                    return;
                                  }
                                  handleDispatchContractor(mTicket, thread.id);
                                }}
                                disabled={isDispatched}
                                className={cn(
                                  "inline-flex items-center justify-center gap-1 px-2 md:px-2.5 py-1.5 md:py-1 rounded-lg md:rounded text-[11.5px] md:text-xs font-semibold transition-colors cursor-pointer truncate",
                                  isDispatched
                                    ? "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                                    : hasContractorContact
                                      ? "bg-[var(--ink)] hover:bg-[var(--ink)]/90 text-white"
                                      : "bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink)] border border-[var(--line)]"
                                )}
                              >
                                <Wrench className="w-3 h-3 text-[var(--accent)] shrink-0" />
                                <span className="truncate">
                                  {isDispatched
                                    ? t("Dispatched")
                                    : hasContractorContact
                                      ? t("Dispatch")
                                      : t("Assign Contractor")}
                                </span>
                              </button>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  );
                })
              ) : (
                <div className="p-6 text-center text-sm text-[var(--ink-3)]">
                  All clear. No messages currently need your action.
                </div>
              )}
            </div>
            {(hiddenCount > 0 || (showAllNeedsYou && needsYouThreads.length > 3 && activeSection === "all")) && (
              <div className="px-4 sm:px-5 py-2.5 border-t border-[var(--line)] bg-[var(--bg)]/50 flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => setShowAllNeedsYou((prev) => !prev)}
                  className="font-semibold text-[var(--ink)] hover:underline cursor-pointer"
                >
                  {showAllNeedsYou
                    ? t("Show fewer")
                    : `${t("View more")} (+${hiddenCount})`}
                </button>
                <Link href="/inbox" className="font-medium text-[var(--accent-ink)] hover:underline">
                  {t("Review all in Inbox →")}
                </Link>
              </div>
            )}
          </section>
            );
          })()}

          {/* Section 1.5: Calendar & Visit Approvals (Top N proposed appointments awaiting Harjot's confirmation) */}
          {(activeSection === "all" || activeSection === "calendar" || activeSection === "needs_you" || activeSection === "urgent") && (
            <CalendarApprovalsCard
              onApproveSuccess={(_eventId, title) => {
                showToast(`Visit approved & synced to Google Calendar: ${title}`);
              }}
              onInviteAnswered={(title, response) => {
                showToast(`Invite ${response}: ${title}`);
              }}
            />
          )}

          {/* Section 2: Waiting on others (Unresponsive cases, Section 2.3 T3 & 5.3) */}
          {(activeSection === "all" || activeSection === "waiting") && (
          <section id="section-waiting" className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title={t("Waiting on others")}
                count={radarItems.length}
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {radarItems.slice(0, activeSection === "all" ? 3 : 50).map((item) => {
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
                        {isNudged ? t("Nudged") : t("Send nudge")}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
          )}

          {/* Section 3: New leads (Inquiries, Section 5.3) */}
          {(activeSection === "all" || activeSection === "leads") && (
          <section id="section-leads" className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)]">
              <SectionHeader
                title={t("New leads")}
                count={leadItems.length}
                actionText={t("Open all →")}
                actionHref="/inbox?audience=inquiries"
              />
            </div>

            <div className="divide-y divide-[var(--line)]">
              {leadItems.length > 0 ? (
                leadItems.map((lead) => (
                  <div
                    key={lead.id}
                    onClick={() => router.push("/inbox?audience=inquiries")}
                    className="p-4 sm:px-5 sm:py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-sm hover:bg-[var(--selected)]/40 transition-colors cursor-pointer"
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
                        {t("Review")}
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="p-6 text-center text-sm text-[var(--ink-3)]">
                  {t("No new leads yet.")}
                </div>
              )}
            </div>
          </section>
          )}

          {/* Bottom Pane: ONE pane, THREE columns separated by 1px vertical lines (Section 5.3 & 3.1) */}
          {(activeSection === "all" || activeSection === "overview") && (
          <section id="section-overview" className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden">
            <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[var(--line)]">

              {/* Column 1: Open rent */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      {t("Open rent")}
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {agingTotal > 0 ? formatCurrency(agingTotal) : "—"}
                    </span>
                  </div>

                  {agingTotal > 0 ? (
                    <>
                      {/* Horizontal Segmented Progress Bar */}
                      <div className="h-2 w-full rounded-full bg-[var(--selected)] overflow-hidden flex mt-3">
                        {agingBuckets.map((b) => (
                          <div key={b.label} style={{ width: `${b.pct}%` }} className={cn(b.barClass, "h-full")} title={`${b.label}: ${b.pct.toFixed(1)}%`} />
                        ))}
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
                    </>
                  ) : (
                    <p className="mt-3 text-xs text-[var(--ink-3)]">No overdue rent recorded. Rent payments are not mirrored yet.</p>
                  )}
                </div>

                <Link
                  href="/money"
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1"
                >
                  <span>{t("Review rent aging")}</span>
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              {/* Column 2: Occupancy */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      {t("Occupancy")}
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {occupancyHeadline}
                    </span>
                  </div>

                  {/* Overall portfolio bar */}
                  {portfolioUnits > 0 && (
                    <div className="mt-3">
                      <div className="h-2 w-full rounded-full overflow-hidden bg-[var(--selected)]">
                        <div
                          className="h-full bg-[var(--ink)] rounded-full transition-all"
                          style={{ width: `${(portfolioOccupied / portfolioUnits) * 100}%` }}
                        />
                      </div>
                      <div className="flex items-center justify-between mt-1 text-[11px] text-[var(--ink-3)]">
                        <span>{portfolioOccupied} of {portfolioUnits} units occupied</span>
                        <span>{portfolioUnits - portfolioOccupied} vacant</span>
                      </div>
                    </div>
                  )}

                  {/* Top buildings with vacancies or largest complexes */}
                  <div className="space-y-2 mt-3 text-xs">
                    {topOccupancyBuildings.map((b) => (
                      <div key={b.name} className="space-y-0.5">
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
                    {remainingBuildingsCount > 0 && (
                      <p className="text-[11px] text-[var(--ink-3)] pt-0.5">
                        +{remainingBuildingsCount} more properties
                      </p>
                    )}
                  </div>
                </div>

                <Link
                  href="/properties"
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1"
                >
                  <span>{portfolio ? `View ${portfolioUnits} units directory` : "View units directory"}</span>
                  <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              {/* Column 3: Handled this week */}
              <div className="p-5 sm:p-6 flex flex-col justify-between space-y-4">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                      {t("Handled this week")}
                    </span>
                    <span className="font-mono text-[15px] font-semibold text-[var(--ink)] tabular-nums">
                      {metrics.autonomousActionsWeek ?? 0}
                    </span>
                  </div>

                  {/* 4 Items stream */}
                  <div className="space-y-2.5 mt-3 text-xs">
                    {logs.length > 0 ? (
                      logs.slice(0, 4).map((log) => (
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
                      ))
                    ) : (
                      <p className="text-xs text-[var(--ink-3)]">No autonomous actions handled yet this week.</p>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => showToast("Opening autonomous operations ledger...")}
                  className="text-xs font-medium text-[var(--ink)] hover:underline underline-offset-4 inline-flex items-center gap-1 pt-1 text-left cursor-pointer"
                >
                  <span>{t("View autonomous ledger")}</span>
                  <ArrowRight className="w-3 h-3" />
                </button>
              </div>

            </div>
          </section>
          )}

        </main>
          </div>

          {/* Ask EstateOS Panel (40% width on right side) */}
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
        </div>
      </div>

      {/* Floating Toast */}
      {toastMessage && (
        <div className="fixed bottom-[calc(4.5rem+env(safe-area-inset-bottom))] left-3.5 right-3.5 md:left-auto md:bottom-6 md:right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[#1a73e8] shrink-0" />
          <span>{toastMessage}</span>
        </div>
      )}



      {/* Floating Mobile Astra Button */}
      {!superAgent.isOpen && (
        <button
          type="button"
          onClick={() => superAgent.setIsOpen(true)}
          className="md:hidden fixed bottom-[calc(4.25rem+env(safe-area-inset-bottom))] right-3.5 z-40 w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-cyan-400 text-white shadow-[0_4px_16px_rgba(0,229,255,0.4)] flex items-center justify-center cursor-pointer hover:scale-105 active:scale-95 transition-all"
          title="Open Astra"
          aria-label="Open Astra"
        >
          <AstraIcon className="w-4 h-4 text-white animate-ai-star" />
        </button>
      )}

      {/* Mobile Bottom Tab Bar */}
      <MobileTabBar pendingCount={currentNeedsYouCount} />

      {/* In-Place Maintenance Ticket Edit Modal */}
      {activeEditTicket && (
        <EditTicketModal
          ticket={activeEditTicket}
          isOpen={isEditModalOpen}
          onClose={() => setIsEditModalOpen(false)}
          onSave={handleSaveTicket}
          onShowToast={showToast}
        />
      )}
    </div>
  );
}
