"use client";

import React, { useState, useMemo, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import {
  Search,
  Check,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  X,
  Phone,
  Mail,
  Calendar,
  FileText,
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  Download,
  Wrench,
  Paperclip,
  MessageSquare,
  Send,
  CheckCheck,
  RotateCw,
  Sparkles,
  CheckCircle2,
  CornerDownRight,
  Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { TenantProfile } from "@/types/portfolio";
import { getTenantProfiles } from "@/lib/portfolioApi";
import { euro, UNKNOWN } from "@/lib/portfolioFormat";
import { PageStateShell } from "@/components/portfolio/PageStateShell";
import { DocumentViewerModal, DocumentItem } from "@/components/ui/DocumentViewerModal";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import {
  ContactEmailItem,
  ContactWhatsAppMessage,
  AIDraftVariant,
} from "@/data/contactsMockData";
import {
  getContactCommunications,
  sendContactWhatsAppMessage,
  generateEmailDrafts,
  sendEmailReply,
  generateWhatsAppDrafts,
} from "@/lib/api";
import { formatClock } from "@/lib/clock";

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function getEmailPriority(email: ContactEmailItem): "emergency" | "high" | "normal" | "low" {
  if (email.priority) return email.priority;
  if (email.category === "maintenance" || email.category === "complaint") return "high";
  if (email.category === "payment") return "normal";
  return "low";
}

function PriorityBadge({ priority }: { priority: "emergency" | "high" | "normal" | "low" }) {
  switch (priority) {
    case "emergency":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-tight bg-red-50 text-red-700 border border-red-200 shrink-0">
          Emergency
        </span>
      );
    case "high":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-tight bg-amber-50 text-amber-700 border border-amber-200 shrink-0">
          High
        </span>
      );
    case "normal":
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-tight bg-blue-50 text-blue-700 border border-blue-200 shrink-0">
          Normal
        </span>
      );
    case "low":
    default:
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-medium uppercase tracking-tight bg-zinc-100 text-zinc-600 border border-zinc-200 shrink-0">
          Low
        </span>
      );
  }
}

function findMatchingTenant(allTenants: TenantProfile[], query: string): TenantProfile | null {
  if (!query) return null;
  const q = query.trim().toLowerCase();
  if (!q) return null;

  const exactId = allTenants.find((t) => t.id.toLowerCase() === q);
  if (exactId) return exactId;

  const byName = allTenants.find((t) => t.name.toLowerCase().includes(q));
  if (byName) return byName;

  const byUnit = allTenants.find(
    (t) =>
      t.unitLabel.toLowerCase().includes(q) ||
      (t.email ?? "").toLowerCase().includes(q) ||
      (q.replace(/[^0-9]/g, "").length >= 4 &&
        (t.phone ?? "").replace(/[^0-9]/g, "").includes(q.replace(/[^0-9]/g, "")))
  );
  if (byUnit) return byUnit;

  return null;
}

function TenantsView({ tenants: MOCK_TENANTS }: { tenants: TenantProfile[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  const tenantParam = searchParams.get("tenant");

  const [activeRentFilter, setActiveRentFilter] = useState<"all" | "up_to_date" | "overdue">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTenantId, setSelectedTenantId] = useState<string>(
    tenantParam || (MOCK_TENANTS.length > 0 ? MOCK_TENANTS[0].id : "")
  );

  const [isProfileExpanded, setIsProfileExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<"mails" | "whatsapp" | "tickets" | "documents">("mails");
  const [activePreviewDoc, setActivePreviewDoc] = useState<DocumentItem | null>(null);

  // Communications state
  const [liveEmails, setLiveEmails] = useState<ContactEmailItem[]>([]);
  const [liveWhatsApp, setLiveWhatsApp] = useState<ContactWhatsAppMessage[]>([]);
  const [whatsAppDrafts, setWhatsAppDrafts] = useState<AIDraftVariant[]>([]);
  const [newWhatsAppMessage, setNewWhatsAppMessage] = useState("");
  const [isSendingWhatsApp, setIsSendingWhatsApp] = useState(false);

  // Email detail & drafts state
  const [openEmailId, setOpenEmailId] = useState<string | null>(null);
  const [emailDraftChoices, setEmailDraftChoices] = useState<Record<string, string>>({});
  const [emailDraftCustomText, setEmailDraftCustomText] = useState<Record<string, string>>({});
  const [isGeneratingEmailDraft, setIsGeneratingEmailDraft] = useState<Record<string, boolean>>({});
  const [isSendingEmailReply, setIsSendingEmailReply] = useState<Record<string, boolean>>({});
  const [mailCategoryFilter, setMailCategoryFilter] = useState<string>("all");
  const [mailPriorityFilter, setMailPriorityFilter] = useState<"all" | "emergency" | "high" | "normal" | "low">("all");
  const [isCategoryMenuOpen, setIsCategoryMenuOpen] = useState(false);
  const [isPriorityMenuOpen, setIsPriorityMenuOpen] = useState(false);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [mailSearch, setMailSearch] = useState("");

  // Derived active tenant
  const activeTenant = useMemo(() => {
    return (
      findMatchingTenant(MOCK_TENANTS, selectedTenantId) ||
      MOCK_TENANTS[0]
    );
  }, [selectedTenantId, MOCK_TENANTS]);

  // Sync state if URL changes
  useEffect(() => {
    if (tenantParam) {
      const matched = findMatchingTenant(MOCK_TENANTS, tenantParam);
      if (matched) {
        setSelectedTenantId(matched.id);
      }
    }
  }, [tenantParam, MOCK_TENANTS]);

  // Update Super Agent Context
  useEffect(() => {
    superAgent.setCurrentPageName("Tenants");
    if (activeTenant) {
      superAgent.setSelectedContext(
        `Tenant: ${activeTenant.name} (${activeTenant.unitLabel}) [Status: ${activeTenant.rentStatus}, Rent: ${euro(activeTenant.monthlyRentEur)}/mo, Phone: ${activeTenant.phone ?? UNKNOWN}, Email: ${activeTenant.email ?? UNKNOWN}]`
      );
    }
  }, [activeTenant?.id]);

  // Live Comms poll for active tenant
  useEffect(() => {
    if (!activeTenant) return;
    let isMounted = true;

    async function fetchLiveComms() {
      if (!activeTenant) return;
      try {
        const comms = await getContactCommunications(
          activeTenant.id,
          activeTenant.email || undefined,
          activeTenant.phone || undefined
        );
        if (isMounted && comms) {
          setLiveEmails(comms.emails || []);
          setLiveWhatsApp(comms.whatsapp_messages || []);
          setWhatsAppDrafts(comms.suggested_whatsapp_drafts || []);
        }
      } catch (err) {
        // Silently preserve current state
      }
    }

    fetchLiveComms();
    const interval = setInterval(fetchLiveComms, 10000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [activeTenant?.id, activeTenant?.email, activeTenant?.phone]);

  // Email draft helpers
  const handleSelectEmailDraft = (emailId: string, variant: AIDraftVariant) => {
    setEmailDraftChoices((prev) => ({ ...prev, [emailId]: variant.id }));
    setEmailDraftCustomText((prev) => ({ ...prev, [emailId]: variant.body }));
  };

  const handleGenerateEmailDrafts = async (email: ContactEmailItem) => {
    if (!activeTenant) return;
    setIsGeneratingEmailDraft((prev) => ({ ...prev, [email.id]: true }));
    try {
      const generated = await generateEmailDrafts(activeTenant.id, email.id);
      if (generated && generated.length > 0) {
        setLiveEmails((prev) =>
          prev.map((e) => (e.id === email.id ? { ...e, draftVariants: generated } : e))
        );
        setEmailDraftChoices((prev) => ({ ...prev, [email.id]: generated[0].id }));
        setEmailDraftCustomText((prev) => ({ ...prev, [email.id]: generated[0].body }));
      }
    } catch (err) {
      console.error("Failed to generate drafts:", err);
    } finally {
      setIsGeneratingEmailDraft((prev) => ({ ...prev, [email.id]: false }));
    }
  };

  const handleSendEmailReply = async (email: ContactEmailItem) => {
    if (!activeTenant) return;
    const textToSend =
      emailDraftCustomText[email.id] !== undefined
        ? emailDraftCustomText[email.id]
        : email.draftVariants?.[0]?.body;

    if (!textToSend || !textToSend.trim() || isSendingEmailReply[email.id]) return;

    setIsSendingEmailReply((prev) => ({ ...prev, [email.id]: true }));
    const replySubject = email.subject.startsWith("Re:") ? email.subject : `Re: ${email.subject}`;

    try {
      const res = await sendEmailReply(
        activeTenant.id,
        email.id,
        replySubject,
        textToSend,
        emailDraftChoices[email.id] || "d1"
      );
      if (res && res.success) {
        const outboundMsg: ContactEmailItem = {
          id: res.message_id,
          sender: "EstateOS (You)",
          senderEmail: "harjot@estateos.internal",
          subject: replySubject,
          snippet: textToSend.slice(0, 100),
          body: textToSend,
          date: "Today",
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          category: email.category,
          priority: getEmailPriority(email),
        };
        setLiveEmails((prev) => [outboundMsg, ...prev]);
        setOpenEmailId(null);
      }
    } catch (err) {
      console.error("Failed to send reply:", err);
    } finally {
      setIsSendingEmailReply((prev) => ({ ...prev, [email.id]: false }));
    }
  };

  // WhatsApp send handler
  const handleSendWhatsApp = async () => {
    if (!activeTenant || !newWhatsAppMessage.trim() || isSendingWhatsApp) return;
    setIsSendingWhatsApp(true);
    const msgText = newWhatsAppMessage.trim();

    try {
      const res = await sendContactWhatsAppMessage(activeTenant.id, msgText);
      if (res.success) {
        const newMsg: ContactWhatsAppMessage = {
          id: res.message_id,
          sender: "owner",
          text: msgText,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          date: "Today",
          status: "sent",
        };
        setLiveWhatsApp((prev) => [...prev, newMsg]);
        setNewWhatsAppMessage("");
      }
    } catch (err) {
      console.error("Failed to send WhatsApp message:", err);
    } finally {
      setIsSendingWhatsApp(false);
    }
  };

  // Filtered tenants list
  const filteredTenants = useMemo(() => {
    return MOCK_TENANTS.filter((tenant) => {
      if (activeRentFilter === "up_to_date" && tenant.rentStatus !== "up_to_date") return false;
      if (activeRentFilter === "overdue" && tenant.rentStatus !== "overdue") return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = tenant.name.toLowerCase().includes(q);
        const matchesUnit = tenant.unitLabel.toLowerCase().includes(q);
        const matchesEmail = (tenant.email || "").toLowerCase().includes(q);
        if (!matchesName && !matchesUnit && !matchesEmail) return false;
      }
      return true;
    });
  }, [MOCK_TENANTS, activeRentFilter, searchQuery]);

  // Filtered emails
  const filteredEmails = useMemo(() => {
    return liveEmails.filter((email) => {
      if (onlyUnread && !email.isUnread) return false;
      if (mailPriorityFilter !== "all" && getEmailPriority(email) !== mailPriorityFilter) {
        return false;
      }
      if (mailCategoryFilter !== "all" && email.category !== mailCategoryFilter) {
        return false;
      }
      if (mailSearch.trim()) {
        const q = mailSearch.toLowerCase();
        const matchesSubject = email.subject.toLowerCase().includes(q);
        const matchesSnippet = email.snippet.toLowerCase().includes(q);
        if (!matchesSubject && !matchesSnippet) return false;
      }
      return true;
    });
  }, [liveEmails, onlyUnread, mailCategoryFilter, mailPriorityFilter, mailSearch]);

  const activeOpenEmail = useMemo(() => {
    if (!openEmailId) return null;
    return liveEmails.find((e) => e.id === openEmailId) || null;
  }, [openEmailId, liveEmails]);

  const overdueCount = useMemo(() => MOCK_TENANTS.filter((t) => t.rentStatus === "overdue").length, [MOCK_TENANTS]);
  const upToDateCount = useMemo(() => MOCK_TENANTS.filter((t) => t.rentStatus === "up_to_date").length, [MOCK_TENANTS]);

  return (
    <div className="flex h-dvh bg-[var(--bg)] overflow-hidden font-sans">
      {/* 1. Global Left Sidebar */}
      <Sidebar />

      {/* 2. Main Workspace Layout with 3 Columns */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopCommandBar />

        <div className="flex-1 flex min-h-0 relative">
          <main className="flex-1 flex min-h-0 overflow-hidden bg-white">
            {/* COLUMN 1: TENANT DIRECTORY (240px) */}
            <div
              className={cn(
                "w-full md:w-[240px] shrink-0 border-r border-[#e8e9eb] bg-[#fafafa] flex flex-col overflow-hidden",
                tenantParam && "hidden md:flex"
              )}
            >
              {/* Header & Filter Pills */}
              <div className="p-[14px_12px_10px] shrink-0 border-b border-[#e8e9eb] space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10.5px] font-bold text-[#64748b] tracking-[0.06em] uppercase">
                    Tenant Directory
                  </div>
                  <span className="text-[10.5px] text-[#94a3b8] font-mono">
                    {MOCK_TENANTS.length} total
                  </span>
                </div>

                {/* Filter Pills */}
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setActiveRentFilter("all")}
                    className={cn(
                      "px-2 py-1 text-[10.5px] font-semibold rounded-[5px] transition-colors cursor-pointer",
                      activeRentFilter === "all"
                        ? "bg-[#0f172a] text-white"
                        : "text-[#64748b] hover:bg-[#e2e8f0]"
                    )}
                  >
                    All ({MOCK_TENANTS.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveRentFilter("up_to_date")}
                    className={cn(
                      "px-2 py-1 text-[10.5px] font-semibold rounded-[5px] transition-colors cursor-pointer",
                      activeRentFilter === "up_to_date"
                        ? "bg-[#0f172a] text-white"
                        : "text-[#64748b] hover:bg-[#e2e8f0]"
                    )}
                  >
                    Up to date ({upToDateCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveRentFilter("overdue")}
                    className={cn(
                      "px-2 py-1 text-[10.5px] font-semibold rounded-[5px] transition-colors cursor-pointer",
                      activeRentFilter === "overdue"
                        ? "bg-[#dc2626] text-white"
                        : "text-[#64748b] hover:bg-[#fee2e2] hover:text-[#dc2626]"
                    )}
                  >
                    Overdue ({overdueCount})
                  </button>
                </div>

                {/* Search Bar */}
                <div className="relative flex items-center">
                  <Search className="w-3.5 h-3.5 text-[#94a3b8] absolute left-2.5 pointer-events-none" />
                  <input
                    type="text"
                    placeholder="Search tenants or units..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full h-[30px] pl-7 pr-3 text-[12px] text-[#111215] bg-white border border-[#d5d9e0] rounded-[6px] outline-none focus:border-[#94a3b8] focus:ring-1 focus:ring-black/5 transition-all placeholder:text-[#94a3b8]"
                  />
                </div>
              </div>

              {/* Tenant items scroll */}
              <div className="flex-1 overflow-y-auto py-1.5">
                {filteredTenants.map((tenant) => {
                  const isSelected = tenant.id === activeTenant?.id;
                  const initials = getInitials(tenant.name);

                  return (
                    <div
                      key={tenant.id}
                      onClick={() => {
                        setSelectedTenantId(tenant.id);
                        setOpenEmailId(null);
                        router.push(`/tenants?tenant=${tenant.id}`);
                      }}
                      className={cn(
                        "flex items-center gap-[9px] px-[10px] py-[7px] mx-[6px] my-[1px] rounded-[6px] cursor-pointer transition-colors select-none",
                        isSelected ? "bg-[#e9eaec]" : "hover:bg-[#eceef1]"
                      )}
                    >
                      {/* Avatar */}
                      <div className="w-[26px] h-[26px] rounded-full bg-[#d5d9e0] text-[#374151] font-bold text-[9px] flex items-center justify-center shrink-0 border-[1.5px] border-[#d5d9e0]">
                        {initials}
                      </div>

                      {/* Name & Unit */}
                      <div className="flex-1 min-w-0 flex flex-col">
                        <div className="flex items-center justify-between gap-1">
                          <span
                            className={cn(
                              "text-[13px] truncate leading-tight",
                              isSelected ? "text-[#0f172a] font-bold" : "text-[#475569] hover:text-[#0f172a]"
                            )}
                          >
                            {tenant.name}
                          </span>
                          <span
                            className={cn(
                              "w-1.5 h-1.5 rounded-full shrink-0",
                              tenant.rentStatus === "overdue" ? "bg-red-500" : "bg-emerald-500"
                            )}
                          />
                        </div>
                        <span className="text-[10.5px] text-[#94a3b8] truncate font-medium mt-0.5">
                          {tenant.unitLabel}
                        </span>
                      </div>
                    </div>
                  );
                })}

                {filteredTenants.length === 0 && (
                  <div className="text-center py-12 text-[#94a3b8] text-xs">
                    No matching tenants found.
                  </div>
                )}
              </div>
            </div>

            {/* COLUMN 2: TENANT DETAIL WORKSPACE (Flex 1) */}
            <div
              className={cn(
                "flex-1 flex flex-col overflow-hidden relative",
                !tenantParam && "hidden md:flex"
              )}
            >
              {/* Back button on mobile */}
              <div className="md:hidden px-4 py-2 border-b border-[#e8e9eb] bg-[#fafafa]">
                <button
                  type="button"
                  onClick={() => router.push("/tenants")}
                  className="inline-flex items-center gap-1.5 text-xs text-[#475569] font-medium"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>All Tenants</span>
                </button>
              </div>

              {!activeTenant ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-[#94a3b8] text-sm bg-white">
                  <p>No tenant selected.</p>
                </div>
              ) : (
                <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
                  {/* Top Executive Profile Card (#f0f5fb subtle blue) */}
                  <div className="bg-[#f0f5fb] border-b border-[#e1e7f0] transition-colors">
                    <div className="flex items-center gap-3.5 px-6 py-3.5 bg-[#f0f5fb]">
                      {/* 44px Avatar */}
                      <div className="w-[44px] h-[44px] rounded-full bg-[#27272a] text-white font-bold text-[15px] flex items-center justify-center shrink-0 border-2 border-[#d5d9e0]">
                        {getInitials(activeTenant.name)}
                      </div>

                      {/* Summary */}
                      <div className="flex-1 min-w-0 flex flex-col gap-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[14px] font-bold text-[#111215] tracking-[-0.01em]">
                            {activeTenant.name}
                          </span>
                          <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize bg-[#f0fdf4] text-[#16a34a] border border-[#bbf7d0]">
                            Tenant
                          </span>
                          <span
                            className={cn(
                              "inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize",
                              activeTenant.rentStatus === "overdue"
                                ? "bg-red-50 text-red-700 border border-red-200"
                                : "bg-emerald-50 text-emerald-700 border border-emerald-200"
                            )}
                          >
                            {activeTenant.rentStatus === "overdue" ? "Rent Overdue" : "Rent up to date"}
                          </span>
                          <span className="text-[11px] text-[#64748b] font-medium">
                            · {activeTenant.unitLabel}
                          </span>
                        </div>

                        {/* Phone + Email + Duration Row */}
                        <div className="flex items-center gap-2.5 flex-wrap text-[11.5px] text-[#4b515d]">
                          {activeTenant.phone && (
                            <>
                              <a
                                href={`tel:${activeTenant.phone}`}
                                className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors"
                              >
                                <Phone className="w-3 h-3 text-[#64748b]" />
                                <span>{activeTenant.phone}</span>
                              </a>
                              <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                            </>
                          )}
                          {activeTenant.email && (
                            <>
                              <a
                                href={`mailto:${activeTenant.email}`}
                                className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors truncate max-w-[220px]"
                              >
                                <Mail className="w-3 h-3 text-[#64748b]" />
                                <span>{activeTenant.email}</span>
                              </a>
                              <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                            </>
                          )}
                          <div className="inline-flex items-center gap-1">
                            <span className="font-semibold text-[#64748b]">Lease Duration:</span>
                            <span className="font-medium text-[#111215]">
                              Since {activeTenant.leaseStart || "01-01-2025"} (to {activeTenant.leaseEnd || "31-12-2026"})
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Expandable address toggle */}
                      <button
                        type="button"
                        onClick={() => setIsProfileExpanded((prev) => !prev)}
                        className="w-7 h-7 rounded-full bg-white border border-[#d5d9e0] text-[#64748b] flex items-center justify-center hover:bg-[#f8fafc] hover:text-[#0f172a] transition-all cursor-pointer shrink-0"
                        title={isProfileExpanded ? "Collapse address details" : "Expand address details"}
                      >
                        {isProfileExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>

                    {/* Expandable Address Details */}
                    {isProfileExpanded && (
                      <div className="px-6 py-2 pb-3.5 bg-[#f0f5fb] border-t border-[#e1e7f0] flex flex-col">
                        <div className="flex items-baseline gap-2 py-1 border-b border-[#e4ecf7]">
                          <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                            Property Address:
                          </span>
                          <span className="text-[12px] text-[#111215] font-medium leading-snug">
                            {activeTenant.unitLabel}, Amsterdam
                          </span>
                        </div>
                        <div className="flex items-baseline gap-2 py-1">
                          <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                            Residential Address:
                          </span>
                          <span className="text-[12px] text-[#111215] font-medium leading-snug">
                            {activeTenant.unitLabel}, Amsterdam, Netherlands
                          </span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* LEASE & TENANCY SPECS GRID (The 6 Exact Metrics) */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-4 bg-white border-b border-[#e5e7eb]">
                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Monthly Rent
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        {euro(activeTenant.monthlyRentEur)}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Security Deposit
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        {euro(activeTenant.depositEur ?? (activeTenant.monthlyRentEur ? activeTenant.monthlyRentEur * 2 : 0))}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Lease Commencement
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        {activeTenant.leaseStart || "01-01-2025"}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Lease Expiry
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        {activeTenant.leaseEnd || "31-12-2026"}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Identity & Vetting
                      </div>
                      <div className="inline-flex items-center gap-1 text-[12px] font-bold text-[#16a34a] mt-1">
                        <ShieldCheck className="w-3.5 h-3.5 text-[#16a34a]" />
                        <span>iDIN Verified</span>
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        Payment Status
                      </div>
                      <div className="text-[12px] font-bold mt-1">
                        {activeTenant.rentStatus === "overdue" ? (
                          <span className="text-red-700">Overdue ({activeTenant.overdueDays}d)</span>
                        ) : (
                          <span className="text-emerald-700">Rent up to date</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Tabs Bar */}
                  <div className="px-6 flex items-center border-b border-[#e5e7eb] bg-white sticky top-0 z-10">
                    <button
                      type="button"
                      onClick={() => setActiveTab("mails")}
                      className={cn(
                        "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                        activeTab === "mails"
                          ? "border-[#0f172a] text-[#0f172a] font-semibold"
                          : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                      )}
                    >
                      <Mail className="w-4 h-4" />
                      <span>Mails</span>
                      {liveEmails.length > 0 && (
                        <span className="text-[10.5px] px-1.5 py-0.2 rounded-full bg-[#f1f5f9] text-[#475569] font-mono">
                          {liveEmails.length}
                        </span>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveTab("whatsapp")}
                      className={cn(
                        "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                        activeTab === "whatsapp"
                          ? "border-[#0f172a] text-[#0f172a] font-semibold"
                          : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                      )}
                    >
                      <MessageSquare className="w-4 h-4" />
                      <span>WhatsApp</span>
                      {liveWhatsApp.length > 0 && (
                        <span className="text-[10.5px] px-1.5 py-0.2 rounded-full bg-[#f1f5f9] text-[#475569] font-mono">
                          {liveWhatsApp.length}
                        </span>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveTab("tickets")}
                      className={cn(
                        "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                        activeTab === "tickets"
                          ? "border-[#0f172a] text-[#0f172a] font-semibold"
                          : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                      )}
                    >
                      <Wrench className="w-4 h-4" />
                      <span>Tickets</span>
                      {activeTenant.name === "Vipin Tyagi" && (
                        <span className="text-[10.5px] px-1.5 py-0.2 rounded-full bg-amber-100 text-amber-800 font-mono">
                          1
                        </span>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveTab("documents")}
                      className={cn(
                        "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                        activeTab === "documents"
                          ? "border-[#0f172a] text-[#0f172a] font-semibold"
                          : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                      )}
                    >
                      <FileText className="w-4 h-4" />
                      <span>Documents</span>
                      <span className="text-[10.5px] px-1.5 py-0.2 rounded-full bg-[#f1f5f9] text-[#475569] font-mono">
                        {activeTenant.documents.length}
                      </span>
                    </button>
                  </div>

                  {/* TAB 1: MAILS */}
                  {activeTab === "mails" && (
                    <div className="flex-1 flex flex-col p-6 space-y-4">
                      {/* Mail Search & Filters Bar */}
                      <div className="flex items-center justify-between gap-3 flex-wrap">
                        <div className="relative flex-1 min-w-[200px]">
                          <Search className="w-3.5 h-3.5 text-[#94a3b8] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                          <input
                            type="text"
                            placeholder="Search emails..."
                            value={mailSearch}
                            onChange={(e) => setMailSearch(e.target.value)}
                            className="w-full h-[32px] pl-8 pr-3 text-[12px] bg-white border border-[#e2e8f0] rounded-[6px] outline-none focus:border-[#94a3b8]"
                          />
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => setOnlyUnread((prev) => !prev)}
                            className={cn(
                              "h-[32px] px-3 text-[11.5px] font-medium rounded-[6px] border transition-colors cursor-pointer",
                              onlyUnread
                                ? "bg-[#0f172a] text-white border-[#0f172a]"
                                : "bg-white text-[#64748b] border-[#e2e8f0] hover:bg-[#f8fafc]"
                            )}
                          >
                            Unread only
                          </button>
                        </div>
                      </div>

                      {/* Email List or Detail */}
                      {activeOpenEmail ? (
                        <div className="border border-[#e2e8f0] rounded-[8px] bg-white p-5 space-y-4">
                          <div className="flex items-center justify-between border-b border-[#e2e8f0] pb-3">
                            <div>
                              <h3 className="text-[14px] font-bold text-[#0f172a]">
                                {activeOpenEmail.subject}
                              </h3>
                              <p className="text-[11.5px] text-[#64748b] mt-0.5">
                                From: {activeOpenEmail.sender} ({activeOpenEmail.senderEmail}) · {activeOpenEmail.date} {activeOpenEmail.time}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => setOpenEmailId(null)}
                              className="px-2.5 py-1 text-xs border border-[#e2e8f0] rounded-[6px] text-[#64748b] hover:bg-[#f8fafc] cursor-pointer"
                            >
                              Close
                            </button>
                          </div>

                          <div className="text-[13px] text-[#334155] leading-relaxed whitespace-pre-wrap py-2">
                            {activeOpenEmail.body || activeOpenEmail.snippet}
                          </div>

                          {/* AI Reply & Drafts */}
                          <div className="border-t border-[#e2e8f0] pt-4 space-y-3">
                            <div className="flex items-center justify-between">
                              <span className="text-[11.5px] font-bold text-[#0f172a] uppercase tracking-wider flex items-center gap-1.5">
                                <Sparkles className="w-3.5 h-3.5 text-[#2563eb]" />
                                AI Draft Responses
                              </span>
                              <button
                                type="button"
                                onClick={() => handleGenerateEmailDrafts(activeOpenEmail)}
                                disabled={isGeneratingEmailDraft[activeOpenEmail.id]}
                                className="text-[11px] font-semibold text-[#2563eb] hover:underline cursor-pointer"
                              >
                                {isGeneratingEmailDraft[activeOpenEmail.id] ? "Drafting..." : "Regenerate variants"}
                              </button>
                            </div>

                            {activeOpenEmail.draftVariants && activeOpenEmail.draftVariants.length > 0 && (
                              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                {activeOpenEmail.draftVariants.map((v) => (
                                  <div
                                    key={v.id}
                                    onClick={() => handleSelectEmailDraft(activeOpenEmail.id, v)}
                                    className={cn(
                                      "p-2.5 rounded-[6px] border text-left cursor-pointer transition-colors text-[11.5px]",
                                      emailDraftChoices[activeOpenEmail.id] === v.id
                                        ? "border-[#2563eb] bg-[#eff6ff] text-[#1e3a8a]"
                                        : "border-[#e2e8f0] bg-white hover:bg-[#f8fafc] text-[#475569]"
                                    )}
                                  >
                                    <div className="font-bold mb-1">{v.label}</div>
                                    <p className="line-clamp-3 text-[11px]">{v.body}</p>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Reply Input Textarea */}
                            <div className="space-y-2 pt-2">
                              <textarea
                                rows={4}
                                value={
                                  emailDraftCustomText[activeOpenEmail.id] !== undefined
                                    ? emailDraftCustomText[activeOpenEmail.id]
                                    : activeOpenEmail.draftVariants?.[0]?.body || ""
                                }
                                onChange={(e) =>
                                  setEmailDraftCustomText((prev) => ({
                                    ...prev,
                                    [activeOpenEmail.id]: e.target.value,
                                  }))
                                }
                                className="w-full p-2.5 text-[12px] border border-[#e2e8f0] rounded-[6px] outline-none focus:border-[#2563eb]"
                                placeholder="Type custom reply or customize the AI draft..."
                              />
                              <div className="flex justify-end">
                                <button
                                  type="button"
                                  onClick={() => handleSendEmailReply(activeOpenEmail)}
                                  disabled={isSendingEmailReply[activeOpenEmail.id]}
                                  className="px-4 py-1.5 rounded-[6px] bg-[#0f172a] text-white text-[12px] font-semibold hover:bg-[#1e293b] transition-colors cursor-pointer"
                                >
                                  {isSendingEmailReply[activeOpenEmail.id] ? "Sending..." : "Approve & Send Reply"}
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="space-y-2">
                          {filteredEmails.map((email) => (
                            <div
                              key={email.id}
                              onClick={() => setOpenEmailId(email.id)}
                              className="p-3.5 rounded-[8px] border border-[#e2e8f0] hover:border-[#cbd5e1] bg-white cursor-pointer transition-all flex items-start justify-between gap-4"
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-[13px] text-[#0f172a] truncate">
                                    {email.subject}
                                  </span>
                                  {email.category && (
                                    <span className="px-1.5 py-0.5 rounded text-[9.5px] font-bold uppercase tracking-wider bg-[#f1f5f9] text-[#475569] border border-[#e2e8f0]">
                                      {email.category}
                                    </span>
                                  )}
                                  <PriorityBadge priority={getEmailPriority(email)} />
                                </div>
                                <p className="text-[12px] text-[#64748b] line-clamp-1 mt-1">
                                  {email.snippet || email.body}
                                </p>
                              </div>
                              <div className="text-[11px] text-[#94a3b8] whitespace-nowrap shrink-0 font-mono">
                                {email.time || email.date}
                              </div>
                            </div>
                          ))}

                          {filteredEmails.length === 0 && (
                            <div className="text-center py-12 text-[#94a3b8] text-xs border border-dashed border-[#e2e8f0] rounded-[8px]">
                              No email messages recorded for this tenant yet.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 2: WHATSAPP */}
                  {activeTab === "whatsapp" && (
                    <div className="flex-1 flex flex-col p-6 max-w-3xl space-y-4">
                      {/* Chat stream */}
                      <div className="flex-1 min-h-[300px] max-h-[500px] overflow-y-auto p-4 border border-[#e2e8f0] rounded-[8px] bg-[#f8fafc] space-y-3">
                        {liveWhatsApp.map((msg) => {
                          const isOwner = msg.sender === "owner";
                          return (
                            <div
                              key={msg.id}
                              className={cn("flex flex-col", isOwner ? "items-end" : "items-start")}
                            >
                              <div
                                className={cn(
                                  "max-w-[75%] p-3 rounded-[10px] text-[12.5px] shadow-2xs leading-relaxed",
                                  isOwner
                                    ? "bg-[#0f172a] text-white rounded-br-none"
                                    : "bg-white text-[#111215] border border-[#e2e8f0] rounded-bl-none"
                                )}
                              >
                                {msg.text}
                              </div>
                              <span className="text-[9.5px] text-[#94a3b8] mt-1 font-mono px-1">
                                {msg.time}
                              </span>
                            </div>
                          );
                        })}

                        {liveWhatsApp.length === 0 && (
                          <div className="text-center py-12 text-[#94a3b8] text-xs">
                            No WhatsApp conversation history recorded yet.
                          </div>
                        )}
                      </div>

                      {/* Quick AI reply chips */}
                      {whatsAppDrafts.length > 0 && (
                        <div className="space-y-1.5">
                          <div className="text-[10.5px] font-bold text-[#64748b] uppercase tracking-wider flex items-center gap-1">
                            <Sparkles className="w-3 h-3 text-[#2563eb]" />
                            Suggested Responses
                          </div>
                          <div className="flex items-center gap-2 flex-wrap">
                            {whatsAppDrafts.map((draft) => (
                              <button
                                key={draft.id}
                                type="button"
                                onClick={() => setNewWhatsAppMessage(draft.body)}
                                className="px-2.5 py-1 text-[11px] rounded-full border border-[#cbd5e1] bg-white text-[#334155] hover:bg-[#f1f5f9] cursor-pointer"
                              >
                                {draft.label}: &quot;{draft.body.slice(0, 30)}...&quot;
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Input bar */}
                      <div className="flex items-center gap-2 pt-1">
                        <input
                          type="text"
                          placeholder="Type a WhatsApp message..."
                          value={newWhatsAppMessage}
                          onChange={(e) => setNewWhatsAppMessage(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              handleSendWhatsApp();
                            }
                          }}
                          className="flex-1 h-[36px] px-3.5 text-[12px] bg-white border border-[#d5d9e0] rounded-[6px] outline-none focus:border-[#0f172a]"
                        />
                        <button
                          type="button"
                          onClick={handleSendWhatsApp}
                          disabled={!newWhatsAppMessage.trim() || isSendingWhatsApp}
                          className="h-[36px] px-4 rounded-[6px] bg-[#0f172a] text-white text-[12px] font-semibold hover:bg-[#1e293b] disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-1.5"
                        >
                          <Send className="w-3.5 h-3.5" />
                          <span>{isSendingWhatsApp ? "Sending..." : "Send"}</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* TAB 3: TICKETS */}
                  {activeTab === "tickets" && (
                    <div className="flex-1 flex flex-col p-6 space-y-4">
                      {activeTenant.name === "Vipin Tyagi" ? (
                        <div className="p-4 rounded-[8px] border border-[#e2e8f0] bg-white space-y-3">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-red-50 text-red-700 border border-red-200">
                                High Urgency
                              </span>
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-800 border border-amber-200">
                                Dispatched
                              </span>
                            </div>
                            <span className="text-[11px] text-[#94a3b8] font-mono">Opened 05 Nov 2026</span>
                          </div>
                          <div>
                            <h4 className="text-[14px] font-bold text-[#0f172a]">
                              Heating System Malfunction
                            </h4>
                            <p className="text-[12.5px] text-[#475569] mt-1 leading-relaxed">
                              Tenant Vipin Tyagi reported that the apartment heating at Keizersgracht 42-A stopped working, causing the unit to become very cold. Contractor Kevin van Dijk (Plumber) has been dispatched via WhatsApp.
                            </p>
                          </div>
                          <div className="text-[11px] text-[#64748b] font-medium pt-2 border-t border-[#f1f5f9]">
                            Unit: Keizersgracht 42-A · Assigned: Kevin van Dijk (Plumber)
                          </div>
                        </div>
                      ) : (
                        <div className="flex-1 flex flex-col items-center justify-center p-12 text-center bg-white border border-dashed border-[#e2e8f0] rounded-[8px]">
                          <div className="w-12 h-12 rounded-full bg-[#f1f5f9] flex items-center justify-center text-[#64748b] mb-3">
                            <Wrench className="w-5 h-5 stroke-[1.5]" />
                          </div>
                          <h3 className="text-sm font-semibold text-[#111215]">No open tickets</h3>
                          <p className="text-xs text-[#64748b] max-w-sm mt-1">
                            There are currently no active maintenance repairs or work orders logged for {activeTenant.name}.
                          </p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB 4: DOCUMENTS */}
                  {activeTab === "documents" && (
                    <div className="flex-1 flex flex-col p-6 space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {activeTenant.documents.map((doc) => (
                          <div
                            key={doc.id}
                            className="p-4 rounded-[8px] border border-[#e2e8f0] bg-white flex items-center justify-between gap-3 hover:border-[#cbd5e1] transition-all"
                          >
                            <div className="flex items-center gap-3 min-w-0">
                              <div className="w-9 h-9 rounded-[6px] bg-[#f1f5f9] flex items-center justify-center text-[#475569] shrink-0">
                                <FileText className="w-4 h-4" />
                              </div>
                              <div className="min-w-0">
                                <h4 className="text-[13px] font-bold text-[#0f172a] truncate">
                                  {doc.title}
                                </h4>
                                <p className="text-[11px] text-[#64748b] mt-0.5 font-mono">
                                  {doc.category.toUpperCase()} · {doc.size} · {doc.date}
                                </p>
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => setActivePreviewDoc(doc)}
                              className="px-3 py-1.5 text-[11px] font-semibold rounded-[5px] border border-[#e2e8f0] text-[#0f172a] hover:bg-[#f8fafc] cursor-pointer shrink-0"
                            >
                              Preview
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </main>

          {/* Consistent Global Super Agent Panel */}
          <AskEstateOSPanel
            currentPageName="Tenants"
            selectedContext={`Tenant Profile: ${activeTenant?.name || "All Tenants"} (${activeTenant?.unitLabel || "N/A"}) · Rent: ${euro(activeTenant?.monthlyRentEur)}/mo · Status: ${activeTenant?.rentStatus || "up_to_date"} · Phone: ${activeTenant?.phone || "N/A"} · Email: ${activeTenant?.email || "N/A"}`}
            onActionTriggered={(actionType, payload) => {
              if (actionType === "navigate" && typeof payload === "string") {
                router.push(payload);
              }
            }}
          />
        </div>
      </div>

      {/* Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* Document Viewer Modal */}
      <DocumentViewerModal
        document={activePreviewDoc}
        onClose={() => setActivePreviewDoc(null)}
        entityName={activeTenant?.name}
        unitLabel={activeTenant?.unitLabel}
      />
    </div>
  );
}

function TenantsContent() {
  const [state, setState] = useState<
    { status: "loading" } | { status: "error" } | { status: "ready"; tenants: TenantProfile[] }
  >({ status: "loading" });

  useEffect(() => {
    let isMounted = true;
    const load = () =>
      getTenantProfiles().then((result) => {
        if (!isMounted) return;
        if (result.ok) setState({ status: "ready", tenants: result.data });
        else setState((prev) => (prev.status === "ready" ? prev : { status: "error" }));
      });
    void load();
    const poll = setInterval(load, 30000);
    return () => {
      isMounted = false;
      clearInterval(poll);
    };
  }, []);

  if (state.status === "loading") return <PageStateShell title="Tenants" message="Loading tenants…" />;
  if (state.status === "error") return <PageStateShell title="Tenants" message="Can't reach the server. Retrying…" alert />;
  if (state.tenants.length === 0) return <PageStateShell title="Tenants" message="No tenants recorded yet." />;
  return <TenantsView tenants={state.tenants} />;
}

export default function TenantsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Tenants...</div>}>
      <TenantsContent />
    </Suspense>
  );
}
