"use client";

import React, { useState, useMemo, useEffect, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import { UrgentLabel } from "@/components/ui/UrgentLabel";
import { StatusText } from "@/components/ui/StatusText";
import {
  Search,
  Check,
  ChevronDown,
  ArrowLeft,
  ArrowUpRight,
  X,
  History,
  Pencil,
  Send,
  Wrench,
  MessageSquare,
  Shield,
  Phone,
  Sparkles,
  Mail,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TicketHistoryModal } from "@/components/maintenance/TicketHistoryModal";
import { EditTicketModal } from "@/components/maintenance/EditTicketModal";
import {
  getMaintenanceTickets,
  approveMaintenanceTicket,
  updateMaintenanceTicket,
} from "@/lib/api";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";

export interface MaintenanceTicket {
  id: string;
  ticketNumber: string;
  issueTitle: string;
  unitLabel: string;
  tenantName: string;
  tenantPhone: string;
  category: "electrical" | "plumbing" | "heating" | "appliance" | "structural";
  contractorName: string;
  contractorTrade: string;
  contractorPhone?: string;
  contractorEmail?: string;
  urgency: "emergency" | "high" | "normal" | "low";
  status: "pending_approval" | "dispatched" | "scheduled" | "completed";
  slaRemaining: string;
  isOverdue?: boolean;
  poBudgetCap: string;
  reportedAt: string;
  notes: string;
  originalMessage?: string;
  tenantDraft?: string;
  contractorDraft?: string;
}

const MOCK_MAINTENANCE_TICKETS: MaintenanceTicket[] = [
  {
    id: "m-1",
    ticketNumber: "#005",
    issueTitle: "Electricity short circuit in kitchen sockets",
    unitLabel: "Pieter Floriszstraat 1 C",
    tenantName: "Pieter Bakker",
    tenantPhone: "+31 6 12 34 41 87",
    category: "electrical",
    contractorName: "Chahal Bouw",
    contractorTrade: "Electrician",
    urgency: "emergency",
    status: "pending_approval",
    slaRemaining: "38m SLA",
    isOverdue: false,
    poBudgetCap: "€ 650",
    reportedAt: "Yesterday 22:10",
    notes: "Fridge warming up after power tripped. Kevin assigned with 11:30 arrival window.",
  },
  {
    id: "m-2",
    ticketNumber: "#010",
    issueTitle: "Washing machine siphon pipe burst and leaking",
    unitLabel: "Dorpsstraat 54 E",
    tenantName: "Rick de Boer",
    tenantPhone: "+31 6 22 41 89 00",
    category: "plumbing",
    contractorName: "Vermeer Loodgieters",
    contractorTrade: "Plumber",
    urgency: "high",
    status: "pending_approval",
    slaRemaining: "1h 14m SLA",
    isOverdue: false,
    poBudgetCap: "€ 450",
    reportedAt: "Today 07:45",
    notes: "Water turned off at main valve. Tenant present after 17:00 for repair.",
  },
  {
    id: "m-3",
    ticketNumber: "#014",
    issueTitle: "Central heating boiler error code F.22",
    unitLabel: "Singel 412",
    tenantName: "Marloes Jansen",
    tenantPhone: "+31 6 44 22 88 19",
    category: "heating",
    contractorName: "Van Dijk CV & Verwarming",
    contractorTrade: "Heating engineer",
    urgency: "emergency",
    status: "scheduled",
    slaRemaining: "12m left",
    isOverdue: true,
    poBudgetCap: "€ 550",
    reportedAt: "Yesterday 18:30",
    notes: "Water pressure dropped to 0.4 bar. Radiator bleed and pump repressurization scheduled.",
  },
  {
    id: "m-4",
    ticketNumber: "#018",
    issueTitle: "Stove ceramic cooktop burner failure",
    unitLabel: "Prinses Marijkestraat 2 A",
    tenantName: "Daan Vermeulen",
    tenantPhone: "+31 6 98 76 54 32",
    category: "appliance",
    contractorName: "KeukenExpert Amsterdam",
    contractorTrade: "Appliance specialist",
    urgency: "normal",
    status: "dispatched",
    slaRemaining: "2 days",
    isOverdue: false,
    poBudgetCap: "€ 480",
    reportedAt: "2 days ago",
    notes: "Replacement induction relay approved and dispatched. Parts arriving Thursday.",
  },
  {
    id: "m-5",
    ticketNumber: "#021",
    issueTitle: "Ground floor main hallway intercom buzzer faulty",
    unitLabel: "Keizersgracht 42-46",
    tenantName: "Multiple residents",
    tenantPhone: "+31 20 000 0001",
    category: "electrical",
    contractorName: "Amstel Elektro",
    contractorTrade: "Electrician",
    urgency: "normal",
    status: "dispatched",
    slaRemaining: "3 days",
    isOverdue: false,
    poBudgetCap: "€ 320",
    reportedAt: "3 days ago",
    notes: "Audio buzzer unlinked from door release solenoid.",
  },
  {
    id: "m-6",
    ticketNumber: "#022",
    issueTitle: "Radiator valve leaking slowly into drip tray",
    unitLabel: "Herengracht 14 B",
    tenantName: "Sophie van Dijk",
    tenantPhone: "+31 6 33 22 11 00",
    category: "heating",
    contractorName: "Van Dijk CV & Verwarming",
    contractorTrade: "Heating engineer",
    urgency: "low",
    status: "scheduled",
    slaRemaining: "4 days",
    isOverdue: false,
    poBudgetCap: "€ 220",
    reportedAt: "4 days ago",
    notes: "Scheduled alongside routine boiler inspection on Friday morning.",
  },
  {
    id: "m-7",
    ticketNumber: "#025",
    issueTitle: "Bathroom sink faucet cartridge replacement",
    unitLabel: "Prinsengracht 118 B",
    tenantName: "Lars de Wit",
    tenantPhone: "+31 6 77 88 99 00",
    category: "plumbing",
    contractorName: "Vermeer Loodgieters",
    contractorTrade: "Plumber",
    urgency: "low",
    status: "completed",
    slaRemaining: "Completed",
    isOverdue: false,
    poBudgetCap: "€ 180",
    reportedAt: "5 days ago",
    notes: "Work completed and verified. Invoice matched PO budget cap.",
  },
  {
    id: "m-8",
    ticketNumber: "#027",
    issueTitle: "Balcony door draught excluder strip replacement",
    unitLabel: "Weteringschans 88",
    tenantName: "Emma Visser",
    tenantPhone: "+31 6 55 44 33 22",
    category: "structural",
    contractorName: "Chahal Bouw",
    contractorTrade: "Carpenter",
    urgency: "low",
    status: "completed",
    slaRemaining: "Completed",
    isOverdue: false,
    poBudgetCap: "€ 140",
    reportedAt: "6 days ago",
    notes: "Weatherstrip fitted. Tenant confirmed satisfaction via WhatsApp.",
  },
];

function findMatchingTicket(allTickets: MaintenanceTicket[], query: string): MaintenanceTicket | null {
  if (!query) return null;
  const qClean = query.replace(/^#/, "").replace(/^case-/, "").trim().toLowerCase();
  if (!qClean) return null;

  // 1. Exact ID or TicketNumber match
  const exact = allTickets.find(
    (t) =>
      t.id.toLowerCase() === query.toLowerCase() ||
      t.id.toLowerCase() === qClean ||
      t.ticketNumber.toLowerCase() === query.toLowerCase() ||
      t.ticketNumber.replace(/^#/, "").toLowerCase() === qClean
  );
  if (exact) return exact;

  // 2. Prefix / substring match on ID or Ticket Number
  const partial = allTickets.find(
    (t) =>
      t.id.toLowerCase().startsWith(qClean) ||
      qClean.startsWith(t.id.toLowerCase()) ||
      t.ticketNumber.toLowerCase().includes(qClean) ||
      t.ticketNumber.replace(/^#/, "").toLowerCase().includes(qClean)
  );
  if (partial) return partial;

  // 3. Fallback: match by unit label or tenant name if search string is a keyword
  if (qClean.length >= 4) {
    const byText = allTickets.find(
      (t) =>
        t.unitLabel.toLowerCase().includes(qClean) ||
        t.tenantName.toLowerCase().includes(qClean)
    );
    if (byText) return byText;
  }

  return null;
}

function MaintenanceContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [tickets, setTickets] = useState<MaintenanceTicket[]>(MOCK_MAINTENANCE_TICKETS);
  const [activeTab, setActiveTab] = useState<"open" | "needs_approval" | "done">("open");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [isStatusDropdownOpen, setIsStatusDropdownOpen] = useState(false);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState<boolean>(false);
  const [isMobile, setIsMobile] = useState<boolean>(false);

  // URL query sync (?ticket=id, Sections 5.6 & 5.6.1)
  const ticketParam = searchParams?.get("ticket") || "";
  const [selectedTicketId, setSelectedTicketId] = useState<string>(ticketParam);

  // Viewport tracking for mobile switching (<1024px)
  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 1024);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Sync ticket param (supports UUID, prefix #01a1, 01a1, mock m-1, address)
  useEffect(() => {
    if (ticketParam) {
      const matched = findMatchingTicket(tickets, ticketParam);
      if (matched) {
        setSelectedTicketId(matched.id);
        // Auto-switch tab if the ticket would be hidden by the current tab
        if (matched.status === "completed" && activeTab === "open") {
          setActiveTab("done");
        } else if (matched.status !== "completed" && activeTab === "done") {
          setActiveTab("open");
        }
      } else {
        setSelectedTicketId(ticketParam);
      }
    }
  }, [ticketParam, tickets, activeTab]);

  // Listen for instant custom navigation events (handles same-page Super Agent clicks)
  useEffect(() => {
    const handleCustomNav = (e: Event) => {
      const customEvent = e as CustomEvent<{ url: string }>;
      const url = customEvent?.detail?.url;
      if (url && url.includes("/maintenance")) {
        const match = url.match(/[?&]ticket=([^&]+)/);
        if (match) {
          const target = decodeURIComponent(match[1]);
          const matched = findMatchingTicket(tickets, target);
          if (matched) {
            setSelectedTicketId(matched.id);
            if (matched.status === "completed" && activeTab === "open") {
              setActiveTab("done");
            } else if (matched.status !== "completed" && activeTab === "done") {
              setActiveTab("open");
            }
          } else {
            setSelectedTicketId(target);
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, [tickets, activeTab]);

  // Close drawer on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && selectedTicketId) {
        handleSelectTicket("");
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedTicketId]);

  // Load live tickets on mount
  useEffect(() => {
    let isMounted = true;
    getMaintenanceTickets()
      .then((res) => {
        if (!isMounted) return;
        if (res.isLive && res.tickets && res.tickets.length > 0) {
          setTickets(res.tickets);
          if (ticketParam) {
            const m = findMatchingTicket(res.tickets, ticketParam);
            if (m) {
              setSelectedTicketId(m.id);
            }
          }
        }
      })
      .catch((err) => console.warn("Failed to load live tickets:", err));
    return () => {
      isMounted = false;
    };
  }, [ticketParam]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const handleSelectTicket = useCallback(
    (id: string) => {
      setSelectedTicketId(id);
      if (id) {
        router.push(`/maintenance?ticket=${encodeURIComponent(id)}`, { scroll: false });
      } else {
        router.push("/maintenance", { scroll: false });
      }
    },
    [router]
  );

  const handleSaveTicket = async (updated: MaintenanceTicket) => {
    setTickets((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    try {
      await updateMaintenanceTicket(updated.id || updated.ticketNumber, {
        issueTitle: updated.issueTitle,
        unitLabel: updated.unitLabel,
        urgency: updated.urgency,
        contractorName: updated.contractorName,
        contractorTrade: updated.contractorTrade,
        contractorPhone: updated.contractorPhone,
        contractorEmail: updated.contractorEmail,
        poBudgetCap: updated.poBudgetCap,
        notes: updated.notes,
        contractorDraft: updated.contractorDraft,
        tenantDraft: updated.tenantDraft,
      });
      showToast(`Ticket ${updated.ticketNumber} saved.`);
    } catch (err) {
      console.warn("Failed to update ticket in backend:", err);
    }
  };

  const handleApproveWorkOrder = async (
    id: string,
    options: { dispatchContractor?: boolean; notifyTenant?: boolean } = {
      dispatchContractor: true,
      notifyTenant: true,
    }
  ) => {
    const target = tickets.find((t) => t.id === id);
    if (!target) return;

    setTickets((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status: "dispatched" } : t))
    );

    const parts: string[] = [];
    const targetEmail = target.contractorEmail || "suryanshtyagi.work@gmail.com";
    if (options.dispatchContractor) {
      parts.push(`Dispatching work order to ${target.contractorName} (${targetEmail})`);
    }
    if (options.notifyTenant) {
      parts.push(`Confirmation sent to ${target.tenantName}`);
    }
    showToast(
      parts.length > 0
        ? `Ticket ${target.ticketNumber}: ${parts.join(" & ")}...`
        : `Ticket ${target.ticketNumber} marked as dispatched.`
    );

    try {
      const res = await approveMaintenanceTicket(target.id || target.ticketNumber, {
        approvalNote: "Authorized by Harjot Singh",
        dispatchContractor: options.dispatchContractor ?? true,
        notifyTenant: options.notifyTenant ?? true,
        contractorMessage: target.contractorDraft,
        tenantMessage: target.tenantDraft,
        poBudgetCap: target.poBudgetCap,
      });
      if (res && res.status === "authorized") {
        showToast(`Real work order email successfully dispatched to ${targetEmail} via Gmail!`);
      }
    } catch (err) {
      console.warn("Dispatch error:", err);
      showToast(`Work order marked dispatched. Verify Gmail dispatch logs.`);
    }
  };

  const handleOpenWhatsAppToContractor = (ticket: MaintenanceTicket) => {
    const rawPhone = ticket.contractorPhone || "+31 6 88 12 34 56";
    const phone = rawPhone.replace(/[^0-9]/g, "");
    if (!phone) return;
    const body = ticket.contractorDraft || `Beste ${ticket.contractorName}, spoedmelding voor ${ticket.unitLabel}: ${ticket.issueTitle}. Geautoriseerd budgetplafond: ${ticket.poBudgetCap}. Gelieve ETA te bevestigen.`;
    const url = `https://wa.me/${phone}?text=${encodeURIComponent(body)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  const handleOpenGmailToContractor = (ticket: MaintenanceTicket) => {
    const email = ticket.contractorEmail || "suryanshtyagi.work@gmail.com";
    const subject = `[Work Order] ${ticket.issueTitle} - ${ticket.unitLabel}`;
    const body = ticket.contractorDraft || `Hi ${ticket.contractorName}, emergency work order for ${ticket.unitLabel}: ${ticket.issueTitle}. Authorized budget cap: ${ticket.poBudgetCap}. Please confirm your earliest ETA.`;
    const url = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(email)}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // 1. Stats calculation (Section 2.4 M2 & 5.4: "4 open · 3 urgent · 1 in progress")
  const openCount = useMemo(
    () => tickets.filter((t) => t.status !== "completed").length,
    [tickets]
  );
  const urgentTicketsCount = useMemo(
    () =>
      tickets.filter(
        (t) =>
          (t.urgency === "emergency" || t.urgency === "high" || t.isOverdue) &&
          t.status !== "completed"
      ).length,
    [tickets]
  );
  const inProgressCount = useMemo(
    () =>
      tickets.filter(
        (t) => t.status === "dispatched" || t.status === "scheduled"
      ).length,
    [tickets]
  );

  // 2. Filter logic: 3 Tabs (Open, Needs approval, Done) + search + status dropdown
  const filteredTickets = useMemo(() => {
    return tickets.filter((t) => {
      // 1. Tab filter
      if (activeTab === "open" && t.status === "completed") return false;
      if (activeTab === "needs_approval" && t.status !== "pending_approval") return false;
      if (activeTab === "done" && t.status !== "completed") return false;

      // 2. Finer status dropdown filter (if not "all")
      if (statusFilter !== "all" && t.status !== statusFilter) return false;

      // 3. Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const match =
          t.ticketNumber.toLowerCase().includes(q) ||
          t.issueTitle.toLowerCase().includes(q) ||
          t.unitLabel.toLowerCase().includes(q) ||
          t.contractorName.toLowerCase().includes(q) ||
          t.tenantName.toLowerCase().includes(q);
        if (!match) return false;
      }

      return true;
    });
  }, [tickets, activeTab, statusFilter, searchQuery]);

  const selectedTicket = useMemo(() => {
    return findMatchingTicket(tickets, selectedTicketId);
  }, [tickets, selectedTicketId]);

  const isMobileDetailOpen = Boolean(selectedTicketId && isMobile);

  const superAgent = useSuperAgent();
  useEffect(() => {
    superAgent.setCurrentPageName("Maintenance");
    if (selectedTicket) {
      superAgent.setSelectedContext(
        `Ticket ${selectedTicket.ticketNumber} · ${selectedTicket.issueTitle} (${selectedTicket.unitLabel}) [Status: ${selectedTicket.status}, Contractor: ${selectedTicket.contractorName}]`
      );
      superAgent.setActiveDrawerInfo({ title: selectedTicket.ticketNumber, kind: "Ticket" });
    } else {
      superAgent.setSelectedContext("Active Maintenance Work Orders (11 open tickets)");
      superAgent.setActiveDrawerInfo(null);
    }
  }, [selectedTicket, superAgent.setCurrentPageName, superAgent.setSelectedContext, superAgent.setActiveDrawerInfo]);

  const getStatusLabel = (t: MaintenanceTicket): string => {
    if (t.status === "completed") return "Done";
    if (t.status === "pending_approval") return "Needs approval";
    if (t.status === "dispatched") return "Dispatched";
    if (t.status === "scheduled") return "Scheduled";
    return String(t.status || "Open");
  };

  const isSlaCritical = (t: MaintenanceTicket) => {
    return t.isOverdue || t.slaRemaining.includes("m") || t.urgency === "emergency";
  };

  return (
    <div className="h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Fixed Sidebar */}
      <Sidebar />

      {/* 2. Main Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-dvh overflow-hidden">
        {/* Top bar hidden on mobile when detail pane is open */}
        <div className={cn(isMobileDetailOpen ? "hidden md:block" : "block")}>
          <TopCommandBar
            pageTitle="Maintenance"
            hideSearch
          />
        </div>

        {/* 3. Maintenance Workspace: Full Width with Right Drawer UI */}
        <div className="flex-1 flex flex-col min-h-0 h-[calc(100dvh-3.5rem)] relative overflow-hidden bg-[var(--pane)]">
          
          {/* Header + Controls + Table / Ticket Rows List */}
          <div className="h-full flex flex-col overflow-hidden bg-[var(--pane)]">
            {/* Header: Title, Inline Stats, Ghost "New ticket" (Section 5.4 & 2.4 M2) */}
            <div className="px-4 sm:px-6 py-3.5 border-b border-[var(--line)] flex flex-wrap items-center justify-between gap-3 shrink-0">
              <div className="min-w-0">
                <div className="flex items-center gap-2.5">
                  <h1 className="font-heading font-bold text-[18px] sm:text-[20px] text-[var(--ink)] tracking-tight leading-tight">
                    Maintenance
                  </h1>
                </div>

                {/* Inline stats (Section 2.4 M2 & 5.4): "4 open · 3 urgent · 1 in progress" */}
                <p className="text-[13px] text-[var(--ink-2)] mt-0.5">
                  <span className="font-medium text-[var(--ink)] tabular-nums">{openCount}</span> open
                  <span className="text-[var(--ink-3)] mx-1.5">·</span>
                  <span className="font-semibold text-[var(--accent-ink)] tabular-nums">{urgentTicketsCount}</span>{" "}
                  <span className="text-[var(--accent-ink)] font-medium">urgent</span>
                  <span className="text-[var(--ink-3)] mx-1.5">·</span>
                  <span className="font-medium text-[var(--ink)] tabular-nums">{inProgressCount}</span> in progress
                </p>
              </div>

              <Button
                variant="ghost"
                size="sm"
                onClick={() => showToast("Opening manual ticket intake drawer...")}
                className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] shadow-2xs shrink-0"
              >
                New ticket
              </Button>
            </div>

            {/* Controls Bar: 3 Tabs (Open, Needs approval, Done) + Search + Status Dropdown (Section 5.4 & 2.4 M4) */}
            <div className="px-4 sm:px-6 py-2.5 border-b border-[var(--line)] bg-[var(--pane)] flex flex-wrap items-center justify-between gap-3 shrink-0 select-none">
              
              {/* 3 Tabs */}
              <div className="flex items-center gap-1">
                {[
                  { id: "open", label: "Open", count: openCount },
                  { id: "needs_approval", label: "Needs approval", count: tickets.filter((t) => t.status === "pending_approval").length },
                  { id: "done", label: "Done" },
                ].map((tab) => {
                  const isActive = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id as any)}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-ctl)] text-[13px] font-medium transition-colors cursor-pointer select-none",
                        isActive
                          ? "bg-[var(--selected)] text-[var(--ink)] font-semibold"
                          : "text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)]/50"
                      )}
                    >
                      <span>{tab.label}</span>
                      {tab.count !== undefined && (
                        <span
                          className={cn(
                            "text-xs px-1.5 py-0.2 rounded-full tabular-nums",
                            tab.id === "needs_approval" && tab.count > 0
                              ? "bg-[var(--accent)] text-[#0A0A0A] font-bold"
                              : "bg-[var(--line)] text-[var(--ink-2)]"
                          )}
                        >
                          {tab.count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Search + Status Dropdown */}
              <div className="flex items-center gap-2 flex-1 sm:flex-initial justify-end">
                {/* Search */}
                <div className="relative flex-1 sm:w-52 md:w-56">
                  <Search className="w-4 h-4 text-[var(--ink-3)] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search tickets..."
                    className="w-full h-8 pl-8 pr-7 text-[13px] bg-[var(--bg)] border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)] transition-colors"
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => setSearchQuery("")}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ink-3)] hover:text-[var(--ink)]"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                {/* Status Dropdown */}
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setIsStatusDropdownOpen((prev) => !prev)}
                    className="h-8 px-2.5 inline-flex items-center gap-1.5 text-xs font-medium text-[var(--ink-2)] border border-[var(--line)] rounded-[var(--radius-ctl)] bg-[var(--pane)] hover:bg-[var(--selected)] transition-colors cursor-pointer select-none"
                  >
                    <span>
                      {statusFilter === "all" ? "All statuses" : statusFilter.replace("_", " ")}
                    </span>
                    <ChevronDown className="w-3 h-3 text-[var(--ink-3)]" />
                  </button>

                  {isStatusDropdownOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-20"
                        onClick={() => setIsStatusDropdownOpen(false)}
                      />
                      <div className="absolute right-0 top-full mt-1.5 w-44 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-ctl)] shadow-lg py-1 z-30 animate-in fade-in zoom-in-95 duration-100 text-xs">
                        {[
                          { id: "all", label: "All statuses" },
                          { id: "pending_approval", label: "Needs approval" },
                          { id: "dispatched", label: "Dispatched" },
                          { id: "scheduled", label: "Scheduled" },
                          { id: "completed", label: "Completed" },
                        ].map((opt) => (
                          <button
                            key={opt.id}
                            type="button"
                            onClick={() => {
                              setStatusFilter(opt.id);
                              setIsStatusDropdownOpen(false);
                            }}
                            className={cn(
                              "w-full text-left px-3 py-1.5 hover:bg-[var(--selected)] flex items-center justify-between transition-colors",
                              statusFilter === opt.id
                                ? "font-semibold text-[var(--ink)] bg-[var(--selected)]/40"
                                : "text-[var(--ink-2)]"
                            )}
                          >
                            <span>{opt.label}</span>
                            {statusFilter === opt.id && <Check className="w-3.5 h-3.5 text-[var(--accent)]" />}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* List / Table Area (The only scrolling part, Section 5.4 & 2.4 M3) */}
            <div className="flex-1 overflow-y-auto pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0">
              
              {/* Desktop Table View (>= 768px): One line per row (56px), Selected = grey with ink left bar, Status always visible, Contractor hidden below 1500px */}
              <div className="hidden md:block w-full">
                <table className="w-full text-left border-collapse table-fixed">
                  <thead>
                    <tr className="border-b border-[var(--line)] text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] bg-[var(--bg)]/90 sticky top-0 z-10">
                      <th className="py-2.5 px-3.5 font-medium w-[32%]">Ticket / Issue</th>
                      <th className="py-2.5 px-3 font-medium w-[18%]">Unit</th>
                      <th className="py-2.5 px-3 font-medium w-[12%]">Category</th>
                      <th className="py-2.5 px-3 font-medium w-[18%]">Contractor</th>
                      <th className="py-2.5 px-3 font-medium w-[10%]">Budget Cap</th>
                      <th className="py-2.5 px-3.5 font-medium text-right w-[10%]">Status / SLA</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--line)] text-[13.5px]">
                    {filteredTickets.map((ticket) => {
                      const isSelected = ticket.id === selectedTicketId;
                      const urgent = ticket.urgency === "emergency" || ticket.urgency === "high" || ticket.isOverdue;

                      return (
                        <tr
                          key={ticket.id}
                          onClick={() => handleSelectTicket(ticket.id)}
                          className={cn(
                            "h-14 cursor-pointer transition-colors group relative",
                            isSelected
                              ? "bg-[var(--selected)] shadow-[inset_3px_0_0_var(--accent-ink)]"
                              : "hover:bg-[var(--selected)]/50"
                          )}
                        >
                          {/* Ticket / Issue */}
                          <td className="px-3.5 py-2 truncate">
                            <div className="flex items-center gap-2 truncate">
                              <span className="font-semibold text-[var(--ink)] shrink-0 font-mono text-[13px]">
                                {ticket.ticketNumber}
                              </span>
                              {urgent && <UrgentLabel />}
                              <span className="text-[var(--ink)] font-medium truncate">
                                {ticket.issueTitle}
                              </span>
                            </div>
                          </td>

                          {/* Unit */}
                          <td className="px-3 py-2 text-[var(--ink-2)] truncate text-[13px]">
                            {ticket.unitLabel}
                          </td>

                          {/* Category */}
                          <td className="px-3 py-2 text-[12px] truncate">
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--bg)] border border-[var(--line)] text-[11px] font-medium text-[var(--ink-2)] capitalize">
                              {ticket.category}
                            </span>
                          </td>

                          {/* Contractor */}
                          <td className="px-3 py-2 text-[13px] truncate">
                            <div className="flex flex-col truncate">
                              <span className="text-[var(--ink)] font-medium truncate">{ticket.contractorName}</span>
                              <span className="text-[var(--ink-3)] text-[11px] truncate">{ticket.contractorTrade}</span>
                            </div>
                          </td>

                          {/* Budget Cap */}
                          <td className="px-3 py-2 font-mono text-[12.5px] text-[var(--ink-2)]">
                            {ticket.poBudgetCap}
                          </td>

                          {/* Status / SLA */}
                          <td className="px-3.5 py-2 text-right whitespace-nowrap">
                            <div className="flex flex-col items-end leading-tight">
                              <StatusText status={getStatusLabel(ticket)} />
                              <span
                                className={cn(
                                  "font-mono text-[11px] mt-0.5",
                                  isSlaCritical(ticket) ? "text-[var(--accent-ink)] font-semibold" : "text-[var(--ink-3)]"
                                )}
                              >
                                {ticket.slaRemaining}
                              </span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Mobile Ticket Rows (< 768px, Section 5.6 & 5.6.1): Line 1: # and issue, Line 2: unit, status, age */}
              <div className="md:hidden divide-y divide-[var(--line)]">
                {filteredTickets.map((ticket) => {
                  const isSelected = ticket.id === selectedTicketId;
                  const urgent = ticket.urgency === "emergency" || ticket.urgency === "high" || ticket.isOverdue;

                  return (
                    <button
                      key={ticket.id}
                      type="button"
                      onClick={() => handleSelectTicket(ticket.id)}
                      className={cn(
                        "w-full text-left p-4 transition-colors cursor-pointer active:bg-[var(--selected)]",
                        isSelected ? "bg-[var(--selected)]" : "bg-[var(--pane)]"
                      )}
                    >
                      {/* Line 1: # and issue */}
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="font-mono font-semibold text-[13.5px] text-[var(--ink)]">
                            {ticket.ticketNumber}
                          </span>
                          <span className="text-[13.5px] font-medium text-[var(--ink)] truncate">
                            {ticket.issueTitle}
                          </span>
                        </div>
                        {urgent && <UrgentLabel />}
                      </div>

                      {/* Line 2: unit, status, age/SLA */}
                      <div className="flex items-center justify-between text-xs text-[var(--ink-3)] mt-1.5">
                        <span className="font-medium text-[var(--ink-2)] truncate max-w-[180px]">
                          {ticket.unitLabel}
                        </span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <StatusText status={getStatusLabel(ticket)} />
                          <span>·</span>
                          <span className={cn("font-mono", isSlaCritical(ticket) ? "text-[var(--accent-ink)] font-semibold" : "text-[var(--ink-3)]")}>
                            {ticket.slaRemaining}
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>

              {filteredTickets.length === 0 && (
                <div className="p-8 text-center text-sm text-[var(--ink-3)]">
                  No tickets found matching the selected filter.
                </div>
              )}
            </div>
          </div>

          {/* Right Drawer Slide-over for Ticket Details */}
          {selectedTicket && (
            <>
              {/* Dimmed Backdrop */}
              <div
                className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 transition-opacity animate-in fade-in duration-200"
                onClick={() => handleSelectTicket("")}
                aria-hidden="true"
              />

              {/* Right Drawer Panel */}
              <aside
                className="fixed inset-y-0 right-0 z-50 w-full sm:w-[560px] md:w-[620px] lg:w-[680px] bg-[var(--pane)] border-l border-[var(--line)] shadow-2xl flex flex-col animate-in slide-in-from-right duration-250 ease-out"
                role="dialog"
                aria-modal="true"
                aria-label={`Ticket ${selectedTicket.ticketNumber} Details`}
              >
                {/* 1. Detail Header (Sticky h-14) */}
                <div className="h-14 px-4 sm:px-6 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between shrink-0 z-10">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <span className="font-mono font-bold text-[15px] text-[var(--ink)]">
                      {selectedTicket.ticketNumber}
                    </span>
                    <span className="text-[var(--line)]">·</span>
                    <span className="text-[13px] text-[var(--ink-2)] font-medium truncate">
                      {selectedTicket.unitLabel}
                    </span>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => setIsEditModalOpen(true)}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11.5px] font-semibold text-[var(--ink)] bg-[var(--bg)] hover:bg-[var(--selected)] border border-[var(--line)] rounded-lg transition-colors cursor-pointer"
                      title="Edit Ticket, Budget Cap, and Drafts"
                    >
                      <Pencil className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                      <span>Edit Ticket</span>
                    </button>

                    {(selectedTicket.urgency === "emergency" || selectedTicket.urgency === "high" || selectedTicket.isOverdue) && (
                      <UrgentLabel />
                    )}
                    <StatusText status={getStatusLabel(selectedTicket)} />

                    {/* Close Drawer Button */}
                    <button
                      type="button"
                      onClick={() => handleSelectTicket("")}
                      className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer ml-1"
                      title="Close drawer (Esc)"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {/* 2. Scrolling Body: Clean, less boxy, full context */}
                <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5 space-y-5 text-xs">
                  {/* Title & Reporter Header */}
                  <div>
                    <h2 className="font-heading font-bold text-[18px] sm:text-[20px] text-[var(--ink)] leading-snug tracking-tight">
                      {selectedTicket.issueTitle}
                    </h2>
                    <p className="text-[12px] text-[var(--ink-3)] mt-1 flex items-center gap-2">
                      <span>Reported {selectedTicket.reportedAt}</span>
                      <span>·</span>
                      <span className="font-medium text-[var(--ink-2)]">{selectedTicket.tenantName}</span>
                      <span>·</span>
                      <span className="font-mono">{selectedTicket.tenantPhone}</span>
                    </p>
                  </div>

                  {/* Original Inbound Tenant Message (Clean, warm, non-boxy) */}
                  <div className="rounded-2xl bg-[var(--bg)]/80 border border-[var(--line)]/70 p-4 space-y-2 select-text shadow-2xs">
                    <div className="flex items-center justify-between text-[11px] font-semibold text-[var(--ink-3)]">
                      <div className="flex items-center gap-1.5 text-[var(--ink-2)]">
                        <MessageSquare className="w-3.5 h-3.5 text-blue-500" />
                        <span>Inbound Tenant Distress Message</span>
                      </div>
                      <span className="text-[10px] font-mono uppercase bg-[var(--pane)] px-2 py-0.5 rounded border border-[var(--line)]">
                        Original Message
                      </span>
                    </div>
                    <p className="text-[13.5px] text-[var(--ink)] leading-relaxed italic">
                      "{selectedTicket.originalMessage || selectedTicket.notes}"
                    </p>
                  </div>

                  {/* Compact Two-Column Grid: Contractor, Budget cap, SLA, Unit */}
                  <div className="rounded-2xl bg-[var(--bg)]/50 border border-[var(--line)]/70 p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)]">
                        Dispatch & PO Authorization
                      </span>
                      <button
                        type="button"
                        onClick={() => setIsEditModalOpen(true)}
                        className="text-[11px] font-semibold text-[var(--accent-ink)] hover:underline cursor-pointer"
                      >
                        Adjust Cap / Contractor
                      </button>
                    </div>

                    <div className="grid grid-cols-2 gap-3.5">
                      {/* Contractor */}
                      <div>
                        <span className="text-[var(--ink-3)] block text-[11px]">Assigned Contractor</span>
                        <div className="flex items-center justify-between gap-1 mt-0.5">
                          <span className="font-semibold text-[var(--ink)] text-[13px] truncate">
                            {selectedTicket.contractorName}
                          </span>
                          <Link
                            href="/inbox?thread=thread-2"
                            className="text-[11px] text-[var(--ink-2)] hover:text-[var(--accent-ink)] inline-flex items-center gap-0.5 font-medium shrink-0"
                            title="Open contractor thread in Inbox"
                          >
                            <span>Chat</span>
                            <ArrowUpRight className="w-3 h-3" />
                          </Link>
                        </div>
                        <span className="text-[var(--ink-3)] text-[11px]">{selectedTicket.contractorTrade} · {selectedTicket.contractorPhone || "+31 6 55 43 21 00"}</span>
                      </div>

                      {/* Budget Cap */}
                      <div>
                        <span className="text-[var(--ink-3)] block text-[11px]">Authorized PO Budget Cap</span>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="font-semibold text-[var(--ink)] font-mono text-[14px]">
                            {selectedTicket.poBudgetCap}
                          </span>
                          <Shield className="w-3.5 h-3.5 text-emerald-600" />
                        </div>
                        <span className="text-[var(--ink-3)] text-[11px]">excl. BTW · Locked ceiling</span>
                      </div>

                      {/* SLA */}
                      <div>
                        <span className="text-[var(--ink-3)] block text-[11px]">SLA Response Window</span>
                        <span
                          className={cn(
                            "font-mono text-[13px] block mt-0.5",
                            isSlaCritical(selectedTicket)
                              ? "font-semibold text-[var(--accent-ink)]"
                              : "text-[var(--ink)] font-medium"
                          )}
                        >
                          {selectedTicket.slaRemaining}
                        </span>
                      </div>

                      {/* Unit */}
                      <div>
                        <span className="text-[var(--ink-3)] block text-[11px]">Property Unit</span>
                        <span className="font-medium text-[var(--ink)] text-[13px] block mt-0.5 truncate">
                          {selectedTicket.unitLabel}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Contractor Work Order Dispatch (Focused exclusively on Contractor) */}
                  <div className="space-y-3 pt-1">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-[var(--ink-3)] block">
                        Contractor Work Order & Dispatch
                      </span>
                      <span className="text-[11px] font-medium text-[var(--ink-2)]">
                        {selectedTicket.contractorName} ({selectedTicket.contractorTrade})
                      </span>
                    </div>

                    {/* Contractor Dispatch Card with Phone & Email */}
                    <div className="rounded-2xl border border-[var(--line)] bg-[var(--bg)]/80 p-4 space-y-3 select-text shadow-2xs">
                      {/* Contractor Contact Header */}
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--line)]/60 pb-3">
                        <div className="flex items-center gap-2">
                          <Wrench className="w-4 h-4 text-[var(--accent-ink)]" />
                          <div>
                            <span className="font-semibold text-[13px] text-[var(--ink)] block">
                              {selectedTicket.contractorName}
                            </span>
                            <span className="text-[11px] text-[var(--ink-3)]">
                              {selectedTicket.contractorTrade} · Approved Partner
                            </span>
                          </div>
                        </div>

                        {/* Direct Communication Channels */}
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1 text-[11.5px] font-mono text-[var(--ink-2)] bg-[var(--pane)] px-2.5 py-1 rounded-md border border-[var(--line)]">
                            <Phone className="w-3 h-3 text-emerald-600" />
                            <span>{selectedTicket.contractorPhone || "+31 6 88 12 34 56"}</span>
                          </span>
                          <span className="inline-flex items-center gap-1 text-[11.5px] font-mono text-[var(--ink-2)] bg-[var(--pane)] px-2.5 py-1 rounded-md border border-[var(--line)]">
                            <Mail className="w-3 h-3 text-blue-600" />
                            <span>{selectedTicket.contractorEmail || "suryanshtyagi.work@gmail.com"}</span>
                          </span>
                        </div>
                      </div>

                      {/* Work Order Staged Message */}
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-semibold text-[var(--ink-3)] uppercase tracking-wider text-[10px]">
                            Staged Work Order Dispatch Text
                          </span>
                          <button
                            type="button"
                            onClick={() => setIsEditModalOpen(true)}
                            className="text-[11px] font-semibold text-[var(--accent-ink)] hover:underline cursor-pointer"
                          >
                            Edit Text
                          </button>
                        </div>
                        <p className="text-[12.5px] text-[var(--ink-2)] leading-relaxed bg-[var(--pane)] p-3 rounded-xl border border-[var(--line)] font-sans">
                          {selectedTicket.contractorDraft ||
                            `Beste ${selectedTicket.contractorName}, spoedmelding voor ${selectedTicket.unitLabel}: ${selectedTicket.issueTitle}. Huurder ${selectedTicket.tenantName} (${selectedTicket.tenantPhone}). Geautoriseerd budgetplafond: ${selectedTicket.poBudgetCap}. Gelieve ETA te bevestigen.`}
                        </p>
                      </div>

                      {/* Quick 1-Click External Dispatch Links */}
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleOpenWhatsAppToContractor(selectedTicket)}
                          className="text-emerald-600 hover:text-emerald-700 bg-emerald-50/60 hover:bg-emerald-100/60 dark:bg-emerald-950/20 dark:hover:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 font-semibold cursor-pointer text-xs"
                          icon={<ExternalLink className="w-3.5 h-3.5 text-emerald-600" />}
                          title="Open WhatsApp Web or App with this work order pre-filled to contractor"
                        >
                          Send via WhatsApp
                        </Button>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleOpenGmailToContractor(selectedTicket)}
                          className="text-blue-600 hover:text-blue-700 bg-blue-50/60 hover:bg-blue-100/60 dark:bg-blue-950/20 dark:hover:bg-blue-950/40 border border-blue-300 dark:border-blue-800 font-semibold cursor-pointer text-xs"
                          icon={<ExternalLink className="w-3.5 h-3.5 text-blue-600" />}
                          title="Open Gmail with this work order pre-filled to contractor"
                        >
                          Send via Gmail
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>

                {/* 3. Sticky Footer in Detail: Full History + Direct Contractor Dispatch */}
                <div className="shrink-0 p-4 border-t border-[var(--line)] bg-[var(--pane)] flex flex-wrap items-center justify-between gap-2.5 select-none pb-[calc(1rem+env(safe-area-inset-bottom))] lg:pb-4">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setIsHistoryModalOpen(true)}
                    icon={<History className="w-4 h-4 text-[var(--ink-3)]" />}
                    className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)]"
                  >
                    History
                  </Button>

                  {selectedTicket.status === "pending_approval" ? (
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleOpenWhatsAppToContractor(selectedTicket)}
                        className="text-xs text-emerald-600 border-emerald-300 dark:border-emerald-800"
                        icon={<ExternalLink className="w-3 h-3 text-emerald-600" />}
                      >
                        WhatsApp
                      </Button>

                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => handleOpenGmailToContractor(selectedTicket)}
                        className="text-xs text-blue-600 border-blue-300 dark:border-blue-800"
                        icon={<ExternalLink className="w-3 h-3 text-blue-600" />}
                      >
                        Email
                      </Button>

                      <Button
                        variant="primary"
                        size="default"
                        onClick={() => handleApproveWorkOrder(selectedTicket.id, { dispatchContractor: true, notifyTenant: false })}
                        icon={<Wrench className="w-3.5 h-3.5 text-[#0A0A0A]" />}
                        className="text-xs font-bold"
                        title="Authorize budget cap and mark work order dispatched"
                      >
                        Authorize & Dispatch PO
                      </Button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 border border-emerald-500/20">
                        <Check className="w-3.5 h-3.5" />
                        <span>Work Order Dispatched to {selectedTicket.contractorName}</span>
                      </span>
                    </div>
                  )}
                </div>
              </aside>
            </>
          )}
        </div>
      </div>

      {/* Full Ticket Lifecycle History Modal */}
      {selectedTicket && (
        <TicketHistoryModal
          ticket={selectedTicket}
          isOpen={isHistoryModalOpen}
          onClose={() => setIsHistoryModalOpen(false)}
          onShowToast={showToast}
        />
      )}

      {/* Edit Ticket & Custom Outbound Messages Modal */}
      {selectedTicket && (
        <EditTicketModal
          ticket={selectedTicket}
          isOpen={isEditModalOpen}
          onClose={() => setIsEditModalOpen(false)}
          onSave={handleSaveTicket}
          onShowToast={showToast}
        />
      )}

      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 bg-[#0A0A0A] text-[#FFFFFF] text-[13px] font-semibold px-4 py-2.5 rounded-[12px] shadow-lg flex items-center gap-2.5 animate-in fade-in slide-in-from-bottom-2 duration-150">
          <Check className="w-4 h-4 text-[#F25C05]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Ask EstateOS Panel */}
      <AskEstateOSPanel
        currentPageName="Maintenance"
        selectedContext={
          selectedTicket
            ? `Ticket ${selectedTicket.ticketNumber} · ${selectedTicket.issueTitle} (${selectedTicket.unitLabel})`
            : "Active Maintenance Work Orders"
        }
        onActionTriggered={(actionType) => {
          showToast(`Action dispatched: ${actionType}`);
        }}
      />

      {/* Mobile Bottom Tab Bar (Hidden on mobile when ticket detail is open) */}
      <MobileTabBar
        className={cn(isMobileDetailOpen ? "hidden" : "grid")}
      />
    </div>
  );
}

export default function MaintenancePage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-[var(--bg)]" />}>
      <MaintenanceContent />
    </Suspense>
  );
}
