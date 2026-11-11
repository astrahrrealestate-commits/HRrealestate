"use client";

import React, { useState, useMemo, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import {
  Search,
  Paperclip,
  Mail,
  MessageSquare,
  FileText,
  Wrench,
  Send,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  ArrowLeft,
  Sparkles,
  RotateCw,
  CheckCircle2,
  CornerDownRight,
  Mic,
  Filter,
  Phone,
  Plus,
  Pencil,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import {
  ContactItem,
  ContactEmailItem,
  ContactWhatsAppMessage,
  AIDraftVariant,
} from "@/data/contactsMockData";
import {
  getContactsList,
  getTenants,
  getContactCommunications,
  sendContactWhatsAppMessage,
  generateEmailDrafts,
  sendEmailReply,
  generateWhatsAppDrafts,
} from "@/lib/api";
import { formatClock } from "@/lib/clock";
import { ContactFormModal } from "@/components/contacts/ContactFormModal";
import type { SavedContact } from "@/lib/contactsWriteApi";

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

function TenantsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantParam = searchParams.get("tenant") || searchParams.get("contact");
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  const [contactForm, setContactForm] = useState<{ open: boolean; contact: ContactItem | null }>({
    open: false,
    contact: null,
  });
  const [searchQuery, setSearchQuery] = useState("");

  // Live Tenants loaded from database directory
  const [dbContacts, setDbContacts] = useState<ContactItem[]>([]);
  const [isLoadingContacts, setIsLoadingContacts] = useState<boolean>(true);

  // A contact just added or classified: show it in the list and open it.
  const handleContactSaved = (saved: SavedContact) => {
    setDbContacts((prev) => {
      const rest = prev.filter((c) => c.id !== saved.id);
      return [...rest, saved].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    });
    setSelectedContactId(saved.id);
    setOpenEmailId(null);
    router.push(`/tenants?tenant=${saved.id}`);
  };

  const [selectedContactId, setSelectedContactId] = useState<string>(
    tenantParam || ""
  );

  useEffect(() => {
    let isMounted = true;
    async function loadTenants() {
      setIsLoadingContacts(true);
      try {
        let list = await getContactsList("tenant");
        if (!list || list.length === 0) {
          const fallback = await getTenants("all");
          if (fallback.data && fallback.data.tenants) {
            list = fallback.data.tenants.map((t: any) => ({
              id: t.id,
              name: t.name,
              category: "tenant",
              tradeOrRole: "Tenant",
              unitRole: t.unitLabel || "Tenant",
              email: t.email || "",
              phone: t.phone || "",
              propertyAddress: t.unitLabel || "",
              residentialAddress: t.unitLabel || "",
              agreementPeriod: t.leaseStart ? `${t.leaseStart} — ${t.leaseEnd}` : "",
              status: "active",
              rentStatus: t.rentStatus || "up_to_date",
              openTicketsCount: 0,
              notes: "",
              trade: "",
              source: "directory",
              unclassified: false,
              documents: [],
              emails: [],
              whatsappMessages: [],
              leases: [],
            }));
          }
        }
        if (isMounted && list) {
          setDbContacts(list);
        }
      } finally {
        if (isMounted) setIsLoadingContacts(false);
      }
    }
    loadTenants();
    return () => { isMounted = false; };
  }, []);

  // Profile Card Collapsed/Expanded state (#f0f5fb subtle blue)
  const [isProfileExpanded, setIsProfileExpanded] = useState(true);

  // Detail pane tabs: "mails" | "whatsapp" | "brixx" | "tickets"
  const [activeTab, setActiveTab] = useState<"mails" | "whatsapp" | "brixx" | "tickets">("mails");

  // Mail filter state: Category & 4 Priorities
  const [mailCategoryFilter, setMailCategoryFilter] = useState<string>("all");
  const [mailPriorityFilter, setMailPriorityFilter] = useState<"all" | "emergency" | "high" | "normal" | "low">("all");
  const [isCategoryMenuOpen, setIsCategoryMenuOpen] = useState(false);
  const [isPriorityMenuOpen, setIsPriorityMenuOpen] = useState(false);
  const [onlyUnread, setOnlyUnread] = useState(false);
  const [mailSearch, setMailSearch] = useState("");

  // Open email thread item
  const [openEmailId, setOpenEmailId] = useState<string | null>(null);

  // Sync state if URL changes or database contacts finish loading
  useEffect(() => {
    if (dbContacts.length === 0) return;
    if (tenantParam && dbContacts.some((c) => c.id === tenantParam)) {
      setSelectedContactId(tenantParam);
    } else if (!dbContacts.some((c) => c.id === selectedContactId)) {
      setSelectedContactId(dbContacts[0].id);
    }
  }, [tenantParam, dbContacts]);

  // Derived active tenant contact
  const activeContact = useMemo(() => {
    if (dbContacts.length === 0) return null;
    return (
      dbContacts.find((c) => c.id === selectedContactId) ||
      dbContacts[0]
    );
  }, [dbContacts, selectedContactId]);

  // Live Communications state (Gmail & WhatsApp)
  const [liveEmails, setLiveEmails] = useState<ContactEmailItem[]>([]);
  const [liveWhatsApp, setLiveWhatsApp] = useState<ContactWhatsAppMessage[]>([]);
  const [whatsappInput, setWhatsappInput] = useState("");
  const [isSendingWhatsApp, setIsSendingWhatsApp] = useState(false);

  // AI Draft Reply State per Email
  const [emailDraftChoices, setEmailDraftChoices] = useState<Record<string, string>>({});
  const [emailDraftCustomText, setEmailDraftCustomText] = useState<Record<string, string>>({});
  const [isGeneratingEmailDraft, setIsGeneratingEmailDraft] = useState<Record<string, boolean>>({});
  const [isSendingEmailReply, setIsSendingEmailReply] = useState<Record<string, boolean>>({});
  const [sentEmailSuccess, setSentEmailSuccess] = useState<Record<string, boolean>>({});

  // WhatsApp Draft State
  const [whatsAppDrafts, setWhatsAppDrafts] = useState<AIDraftVariant[]>([]);
  const [isGeneratingWhatsAppDrafts, setIsGeneratingWhatsAppDrafts] = useState(false);

  // Update Super Agent Context
  useEffect(() => {
    superAgent.setCurrentPageName("Tenants");
    if (activeContact) {
      superAgent.setSelectedContext(
        `Tenant Profile: ${activeContact.name} · Unit: ${activeContact.unitRole || "N/A"} · Phone: ${activeContact.phone} · Email: ${activeContact.email}`
      );
    }
  }, [activeContact?.id]);

  // Fetch Live Communications when active tenant changes
  useEffect(() => {
    if (!activeContact) return;
    let isMounted = true;

    async function fetchLiveComms() {
      if (!activeContact) return;
      try {
        const comms = await getContactCommunications(
          activeContact.id,
          activeContact.email || undefined,
          activeContact.phone || undefined
        );
        if (isMounted && comms) {
          setLiveEmails(comms.emails || []);
          setLiveWhatsApp(comms.whatsapp_messages || []);
          setWhatsAppDrafts(comms.suggested_whatsapp_drafts || []);
        }
      } catch (err) {
        // Silently preserve current state when backend is offline
      }
    }

    fetchLiveComms();
    const interval = setInterval(fetchLiveComms, 8000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [activeContact?.id, activeContact?.email, activeContact?.phone]);

  const handleSelectEmailDraft = (emailId: string, variant: AIDraftVariant) => {
    setEmailDraftChoices((prev) => ({ ...prev, [emailId]: variant.id }));
    setEmailDraftCustomText((prev) => ({ ...prev, [emailId]: variant.body }));
  };

  const handleGenerateEmailDrafts = async (email: ContactEmailItem) => {
    if (!activeContact) return;
    setIsGeneratingEmailDraft((prev) => ({ ...prev, [email.id]: true }));
    try {
      const generated = await generateEmailDrafts(activeContact.id, email.id);
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
    if (!activeContact) return;
    const textToSend =
      emailDraftCustomText[email.id] !== undefined
        ? emailDraftCustomText[email.id]
        : email.draftVariants?.[0]?.body;

    if (!textToSend || !textToSend.trim() || isSendingEmailReply[email.id]) return;

    setIsSendingEmailReply((prev) => ({ ...prev, [email.id]: true }));
    const replySubject = email.subject.startsWith("Re:") ? email.subject : `Re: ${email.subject}`;

    try {
      const res = await sendEmailReply(
        activeContact.id,
        email.id,
        replySubject,
        textToSend,
        emailDraftChoices[email.id] || "d1"
      );
      if (res && res.success) {
        setSentEmailSuccess((prev) => ({ ...prev, [email.id]: true }));
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

  const handleSendWhatsApp = async () => {
    if (!activeContact || !whatsappInput.trim() || isSendingWhatsApp) return;
    setIsSendingWhatsApp(true);
    const text = whatsappInput.trim();

    try {
      const res = await sendContactWhatsAppMessage(activeContact.id, text);
      if (res && res.success) {
        const newMsg: ContactWhatsAppMessage = {
          id: res.message_id,
          sender: "owner",
          text: text,
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          date: "Today",
          status: "sent",
        };
        setLiveWhatsApp((prev) => [...prev, newMsg]);
        setWhatsappInput("");
      }
    } catch (err) {
      console.error("Failed to send WhatsApp message:", err);
    } finally {
      setIsSendingWhatsApp(false);
    }
  };

  const handleGenerateWhatsAppDrafts = async () => {
    if (!activeContact || isGeneratingWhatsAppDrafts) return;
    setIsGeneratingWhatsAppDrafts(true);
    try {
      const drafts = await generateWhatsAppDrafts(activeContact.id);
      if (drafts && drafts.length > 0) {
        setWhatsAppDrafts(drafts);
      }
    } catch (err) {
      console.error("Failed to generate WhatsApp drafts:", err);
    } finally {
      setIsGeneratingWhatsAppDrafts(false);
    }
  };

  // Filtered contacts list
  const filteredContacts = useMemo(() => {
    return dbContacts.filter((contact) => {
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        const matchesName = contact.name.toLowerCase().includes(q);
        const matchesEmail = (contact.email ?? "").toLowerCase().includes(q);
        const matchesUnit = (contact.unitRole || "").toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesUnit) return false;
      }
      return true;
    });
  }, [dbContacts, searchQuery]);

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
        const matchesCategory = (email.category || "").toLowerCase().includes(q);
        if (!matchesSubject && !matchesSnippet && !matchesCategory) return false;
      }
      return true;
    });
  }, [liveEmails, onlyUnread, mailCategoryFilter, mailPriorityFilter, mailSearch]);

  const activeOpenEmail = useMemo(() => {
    if (!openEmailId) return null;
    return liveEmails.find((e) => e.id === openEmailId) || null;
  }, [openEmailId, liveEmails]);

  return (
    <div className="flex h-dvh bg-[var(--bg)] overflow-hidden font-sans">
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <TopCommandBar />

        <div className="flex-1 flex min-h-0 relative">
          <main className="flex-1 flex min-h-0 overflow-hidden bg-white">
            {/* PANEL 1: TENANT LIST (220px) */}
            <div
              className={cn(
                "w-full md:w-[220px] shrink-0 border-r border-[#e8e9eb] bg-[#fafafa] flex flex-col overflow-hidden",
                tenantParam && "hidden md:flex"
              )}
            >
              {/* Header */}
              <div className="p-[14px_12px_10px] shrink-0 border-b border-[#e8e9eb] space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10.5px] font-bold text-[#64748b] tracking-[0.06em] uppercase">
                    Tenants
                  </div>
                  <button
                    type="button"
                    onClick={() => setContactForm({ open: true, contact: null })}
                    title="Add tenant"
                    aria-label="Add tenant"
                    className="inline-flex items-center gap-1 h-[22px] px-2 rounded-[6px] bg-[#111215] text-white text-[10.5px] font-semibold hover:bg-[#27272a] transition-colors cursor-pointer"
                  >
                    <Plus className="w-3 h-3" />
                    <span>Add</span>
                  </button>
                </div>

                {/* Search Bar */}
                <div className="relative flex items-center">
                  <Search className="w-3.5 h-3.5 text-[#94a3b8] absolute left-2.5 pointer-events-none" />
                  <input
                    type="text"
                    placeholder={t("Search...")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full h-[30px] pl-7 pr-3 text-[12px] text-[#111215] bg-white border border-[#d5d9e0] rounded-[6px] outline-none focus:border-[#94a3b8] focus:ring-1 focus:ring-black/5 transition-all placeholder:text-[#94a3b8]"
                  />
                </div>
              </div>

              {/* Contact items scroll */}
              <div className="flex-1 overflow-y-auto py-1.5">
                {isLoadingContacts && dbContacts.length === 0 && (
                  <div className="p-3 space-y-2">
                    {[1, 2, 3, 4].map((i) => (
                      <div key={i} className="h-9 bg-zinc-200/50 animate-pulse rounded-[6px]" />
                    ))}
                  </div>
                )}

                {filteredContacts.map((contact) => {
                  const isSelected = contact.id === activeContact?.id;
                  const initials = getInitials(contact.name);

                  return (
                    <div
                      key={contact.id}
                      onClick={() => {
                        setSelectedContactId(contact.id);
                        setOpenEmailId(null);
                        router.push(`/tenants?tenant=${contact.id}`);
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
                        <span
                          className={cn(
                            "text-[13px] truncate leading-tight flex items-center justify-between",
                            isSelected ? "text-[#0f172a] font-bold" : "text-[#475569] hover:text-[#0f172a]"
                          )}
                        >
                          <span className="truncate">{contact.name}</span>
                          {contact.rentStatus === "overdue" && (
                            <span className="shrink-0 text-[9.5px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 px-1.5 py-0.2 rounded-full uppercase ml-1">
                              {t("Overdue", "Overdue")}
                            </span>
                          )}
                        </span>
                        {contact.tradeOrRole && (
                          <span className="text-[10.5px] text-[#94a3b8] truncate font-medium mt-0.5">
                            {contact.unitRole || contact.tradeOrRole}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {!isLoadingContacts && filteredContacts.length === 0 && (
                  <div className="text-center py-12 text-[#94a3b8] text-xs">
                    No tenants found.
                  </div>
                )}
              </div>
            </div>

            {/* PANEL 2: TENANT DETAIL */}
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

              {!activeContact ? (
                <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-[#94a3b8] text-sm bg-white">
                  {isLoadingContacts ? (
                    <div className="flex items-center gap-2 text-xs text-[#64748b]">
                      <RotateCw className="w-4 h-4 animate-spin text-[#1a73e8]" />
                      <span>Loading database directory...</span>
                    </div>
                  ) : (
                    <p>No tenant selected.</p>
                  )}
                </div>
              ) : (
                <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
                  {/* Profile Card (Matching subtle blue #f0f5fb for top and expanded body) */}
                  <div className="bg-[#f0f5fb] border-b border-[#e1e7f0] transition-colors">
                    <div className="flex items-center gap-3.5 px-6 py-3.5 bg-[#f0f5fb]">
                      {/* 44px Avatar */}
                      <div className="w-[44px] h-[44px] rounded-full bg-[#27272a] text-white font-bold text-[15px] flex items-center justify-center shrink-0 border-2 border-[#d5d9e0]">
                        {getInitials(activeContact.name)}
                      </div>

                      {/* Summary */}
                      <div className="flex-1 min-w-0 flex flex-col gap-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[14px] font-bold text-[#111215] tracking-[-0.01em]">
                            {activeContact.name}
                          </span>
                          <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize bg-[#f0fdf4] text-[#16a34a] border border-[#bbf7d0]">
                            Tenant
                          </span>
                          {activeContact.rentStatus === "overdue" ? (
                            <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize bg-[#fef2f2] text-[#dc2626] border border-[#fecaca]">
                              {t("Rent overdue", "Rent overdue")}
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize bg-[#f0fdf4] text-[#16a34a] border border-[#bbf7d0]">
                              {t("Rent up to date", "Rent up to date")}
                            </span>
                          )}
                          {activeContact.unitRole && (
                            <span className="text-[11px] text-[#64748b] font-medium">
                              · {activeContact.unitRole}
                            </span>
                          )}
                        </div>

                        {/* Phone + Email + Agreement Inline Row */}
                        <div className="flex items-center gap-2.5 flex-wrap text-[11.5px] text-[#4b515d]">
                          {activeContact.phone && (
                            <>
                              <a
                                href={`tel:${activeContact.phone}`}
                                className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors"
                              >
                                <Phone className="w-3 h-3 text-[#64748b]" />
                                <span>{activeContact.phone}</span>
                              </a>
                              <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                            </>
                          )}
                          {activeContact.email && (
                            <>
                              <a
                                href={`mailto:${activeContact.email}`}
                                className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors truncate max-w-[220px]"
                              >
                                <Mail className="w-3 h-3 text-[#64748b]" />
                                <span>{activeContact.email}</span>
                              </a>
                              <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                            </>
                          )}
                          <div className="inline-flex items-center gap-1">
                            <span className="font-semibold text-[#64748b]">Agreement Duration:</span>
                            <span className="font-medium text-[#111215]">
                              {activeContact.agreementPeriod || "Since 01 Jan 2025 (to 31 Dec 2026)"}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Chevron Toggle Button */}
                      <button
                        type="button"
                        onClick={() => setIsProfileExpanded((prev) => !prev)}
                        className="w-7 h-7 rounded-full bg-white border border-[#d5d9e0] text-[#64748b] flex items-center justify-center hover:bg-[#f8fafc] hover:text-[#0f172a] transition-all cursor-pointer shrink-0"
                        title={isProfileExpanded ? "Collapse address details" : "Expand address details"}
                      >
                        {isProfileExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>

                    {/* Expandable details */}
                    {isProfileExpanded && (
                      <div className="px-6 py-2 pb-3.5 bg-[#f0f5fb] border-t border-[#e1e7f0] flex flex-col">
                        <div className="flex items-baseline gap-2 py-1 border-b border-[#e4ecf7]">
                          <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                            {t("Property Address:")}
                          </span>
                          <span className="text-[12px] text-[#111215] font-medium leading-snug">
                            {activeContact.propertyAddress || activeContact.address || "Keizersgracht 42, 1015 CR Amsterdam"}
                          </span>
                        </div>
                        <div className="flex items-baseline gap-2 py-1">
                          <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                            {t("Residential Address:")}
                          </span>
                          <span className="text-[12px] text-[#111215] font-medium leading-snug">
                            {activeContact.residentialAddress || activeContact.address || "Keizersgracht 42, 1015 CR Amsterdam"}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* LEASE & TENANCY SPECS (All 6 requested metrics) */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-4 bg-white border-b border-[#e5e7eb]">
                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Monthly Rent")}
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        € 2.450,-
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Security Deposit")}
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        € 4.900,-
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Lease Commencement")}
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        01-01-2025
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Lease Expiry")}
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        31-12-2026
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Identity & Vetting")}
                      </div>
                      <div className="inline-flex items-center gap-1 text-[12px] font-bold text-[#16a34a] mt-1">
                        <ShieldCheck className="w-3.5 h-3.5 text-[#16a34a]" />
                        <span>{t("iDIN Verified")}</span>
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Payment Status")}
                      </div>
                      <div className="text-[12px] font-bold text-emerald-700 mt-1">
                        {t("Rent up to date")}
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
                      <span>{t("Mails")}</span>
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
                      <span>{t("WhatsApp")}</span>
                      {liveWhatsApp.length > 0 && (
                        <span className="text-[10.5px] px-1.5 py-0.2 rounded-full bg-[#f1f5f9] text-[#475569] font-mono">
                          {liveWhatsApp.length}
                        </span>
                      )}
                    </button>

                    <button
                      type="button"
                      onClick={() => setActiveTab("brixx")}
                      className={cn(
                        "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                        activeTab === "brixx"
                          ? "border-[#0f172a] text-[#0f172a] font-semibold"
                          : "border-transparent text-[#64748b] hover:text-[#0f172a]"
                      )}
                    >
                      <FileText className="w-4 h-4" />
                      <span>{t("Brixx")}</span>
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
                      <span>{t("Tickets")}</span>
                    </button>
                  </div>

                  {/* TAB VIEW 1: Mails (Gmail-style) */}
                  {activeTab === "mails" && (
                    <div className="flex-1 flex flex-col bg-white">
                      {/* Search & Action Bar */}
                      <div className="px-6 py-3 border-b border-[#e5e7eb] flex items-center justify-between gap-3 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                          {/* Category Filter */}
                          <div className="relative">
                            <button
                              type="button"
                              onClick={() => {
                                setIsCategoryMenuOpen((prev) => !prev);
                                setIsPriorityMenuOpen(false);
                              }}
                              className={cn(
                                "inline-flex items-center gap-1 h-[27px] px-[11px] text-[11.5px] font-medium rounded-full transition-all cursor-pointer whitespace-nowrap",
                                mailCategoryFilter !== "all"
                                  ? "bg-[#0f172a] text-white font-semibold"
                                  : "bg-white text-[#4b515d] border border-[#e5e7eb] hover:bg-[#f8fafc] hover:text-[#111215]"
                              )}
                            >
                              <span>{mailCategoryFilter === "all" ? t("Category") : `${t("Category")}: ${t(mailCategoryFilter)}`}</span>
                              <ChevronDown className="w-2.5 h-2.5 opacity-70" />
                            </button>

                            {isCategoryMenuOpen && (
                              <div className="absolute top-[calc(100%+5px)] left-0 min-w-[150px] bg-white border border-[#e2e8f0] rounded-[8px] shadow-[0_8px_24px_rgba(15,23,42,0.1)] p-1 z-50 flex flex-col">
                                {["all", "lease", "payment", "maintenance", "complaint", "admin"].map((cat) => (
                                  <button
                                    key={cat}
                                    type="button"
                                    onClick={() => {
                                      setMailCategoryFilter(cat);
                                      setIsCategoryMenuOpen(false);
                                    }}
                                    className={cn(
                                      "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left capitalize transition-colors cursor-pointer",
                                      mailCategoryFilter === cat
                                        ? "bg-[#f8fafc] text-[#0f172a] font-semibold"
                                        : "text-[#334155] hover:bg-[#f1f5f9] hover:text-[#0f172a]"
                                    )}
                                  >
                                    {cat === "all" ? t("All Categories") : t(cat)}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>

                          {/* Unread Toggle */}
                          <button
                            type="button"
                            onClick={() => setOnlyUnread((prev) => !prev)}
                            className={cn(
                              "inline-flex items-center gap-1 h-[27px] px-[11px] text-[11.5px] font-medium rounded-full transition-all cursor-pointer whitespace-nowrap",
                              onlyUnread
                                ? "bg-[#0f172a] text-white font-semibold shadow-2xs"
                                : "bg-white text-[#4b515d] border border-[#e5e7eb] hover:bg-[#f8fafc] hover:text-[#111215]"
                            )}
                          >
                            <span>{t("Unread")}</span>
                          </button>
                        </div>

                        {/* Search in Emails */}
                        <div className="relative w-full sm:w-[220px]">
                          <Search className="w-3.5 h-3.5 text-[#94a3b8] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                          <input
                            type="text"
                            placeholder={t("Search in emails...")}
                            value={mailSearch}
                            onChange={(e) => setMailSearch(e.target.value)}
                            className="w-full h-[28px] pl-7 pr-3 text-[11.5px] bg-white border border-[#d5d9e0] rounded-[5px] outline-none focus:border-[#94a3b8] focus:ring-1 focus:ring-black/5"
                          />
                        </div>
                      </div>

                      {/* Detail View of an Opened Email */}
                      {activeOpenEmail ? (
                        <div className="p-6 space-y-4">
                          <button
                            type="button"
                            onClick={() => setOpenEmailId(null)}
                            className="inline-flex items-center gap-1.5 text-xs text-[#475569] font-medium hover:text-[#0f172a] mb-2 cursor-pointer"
                          >
                            <ArrowLeft className="w-3.5 h-3.5" />
                            <span>{t("Back to messages")}</span>
                          </button>

                          <div className="border border-[#e2e8f0] rounded-xl p-5 bg-white space-y-4 shadow-2xs">
                            <div className="flex items-start justify-between gap-4 border-b border-[#f1f5f9] pb-4">
                              <div>
                                <h3 className="text-base font-bold text-[#0f172a]">
                                  {activeOpenEmail.subject}
                                </h3>
                                <div className="flex items-center gap-2 mt-1 text-xs text-[#64748b]">
                                  <span className="font-semibold text-[#1e293b]">
                                    {activeOpenEmail.sender}
                                  </span>
                                  <span>&lt;{activeOpenEmail.senderEmail}&gt;</span>
                                  <span>•</span>
                                  <span>{activeOpenEmail.date} at {activeOpenEmail.time}</span>
                                </div>
                              </div>
                              <PriorityBadge priority={getEmailPriority(activeOpenEmail)} />
                            </div>

                            <div className="text-[13px] text-[#334155] leading-relaxed whitespace-pre-wrap py-2">
                              {activeOpenEmail.body}
                            </div>

                            {/* AI Draft Response Variants */}
                            <div className="border-t border-[#f1f5f9] pt-4 space-y-3">
                              <div className="flex items-center justify-between">
                                <span className="text-xs font-bold text-[#0f172a] uppercase tracking-wider flex items-center gap-1.5">
                                  <Sparkles className="w-3.5 h-3.5 text-[#2563eb]" />
                                  AI Suggested Replies
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
                                        "p-3 rounded-lg border text-left cursor-pointer transition-colors text-[11.5px]",
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
                        </div>
                      ) : (
                        /* Email list view */
                        <div className="divide-y divide-[#f1f5f9]">
                          {filteredEmails.map((email) => (
                            <div
                              key={email.id}
                              onClick={() => setOpenEmailId(email.id)}
                              className="px-6 py-3.5 hover:bg-[#f8fafc] cursor-pointer transition-colors flex items-center justify-between gap-4"
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-[13px] text-[#0f172a] truncate">
                                    {email.subject}
                                  </span>
                                  {email.category && (
                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[#f1f5f9] text-[#475569] border border-[#e2e8f0] uppercase tracking-wider">
                                      {email.category}
                                    </span>
                                  )}
                                  <PriorityBadge priority={getEmailPriority(email)} />
                                </div>
                                <p className="text-[12px] text-[#64748b] truncate mt-0.5">
                                  {email.snippet || email.body}
                                </p>
                              </div>
                              <span className="text-[11px] text-[#94a3b8] font-mono shrink-0">
                                {email.time || email.date}
                              </span>
                            </div>
                          ))}

                          {filteredEmails.length === 0 && (
                            <div className="text-center py-20 text-[#94a3b8] text-xs">
                              No email messages on file for this tenant.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB VIEW 2: WhatsApp Chat */}
                  {activeTab === "whatsapp" && (
                    <div className="flex-1 flex flex-col min-h-[500px] bg-[#e5ddd5] overflow-hidden">
                      <div className="flex-1 overflow-y-auto p-4 sm:p-5 flex flex-col gap-2.5">
                        {liveWhatsApp && liveWhatsApp.length > 0 ? (
                          liveWhatsApp.map((msg) => {
                            const isTenant = msg.sender === "tenant";

                            return (
                              <div
                                key={msg.id}
                                className={cn(
                                  "flex flex-col max-w-[72%]",
                                  isTenant ? "mr-auto items-start" : "ml-auto items-end"
                                )}
                              >
                                <div
                                  className={cn(
                                    "px-3 py-2 rounded-[8px] text-[13px] leading-relaxed shadow-xs break-words",
                                    isTenant
                                      ? "bg-white text-[#111215] rounded-tl-[2px]"
                                      : "bg-[#e2f7cb] text-[#111215] rounded-tr-[2px]"
                                  )}
                                >
                                  {msg.text}
                                </div>
                                <div className="flex items-center gap-1 text-[10px] text-black/40 font-mono mt-0.5 px-1 self-end">
                                  <span>{msg.time}</span>
                                  {!isTenant && <CheckCheck className="w-3 h-3 text-[#2563eb]" />}
                                </div>
                              </div>
                            );
                          })
                        ) : (
                          <div className="text-center py-20 text-[#64748b] text-xs">
                            No previous WhatsApp messages recorded in database for this tenant.
                          </div>
                        )}
                      </div>

                      {/* WhatsApp Chat Bar — Subtle AI Blue theme */}
                      <div className="p-3 bg-[#f0f7ff] border-t border-[#bfdbfe] flex flex-col gap-2 shrink-0">
                        <div className="flex items-center justify-between gap-2 flex-wrap px-1">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <span className="text-[11px] font-semibold text-[#1d4ed8] flex items-center gap-1">
                              <Sparkles className="w-3 h-3 text-[#2563eb] animate-wa-sparkle" />
                              AI Draft:
                            </span>
                            {whatsAppDrafts.length > 0 ? (
                              whatsAppDrafts.map((d, i) => (
                                <button
                                  key={d.id || i}
                                  type="button"
                                  onClick={() => setWhatsappInput(d.body)}
                                  className="inline-flex items-center gap-1 h-[26px] px-2.5 rounded-full text-[11px] font-semibold bg-[#eff6ff] hover:bg-[#dbeafe] border border-[#bfdbfe] text-[#1d4ed8] transition-all cursor-pointer shadow-2xs"
                                  title={d.body}
                                >
                                  <span>{d.label || `Draft ${i + 1}`}</span>
                                </button>
                              ))
                            ) : (
                              <span className="text-[11px] text-[#64748b]">Click generate for suggested replies</span>
                            )}
                          </div>

                          <button
                            type="button"
                            onClick={handleGenerateWhatsAppDrafts}
                            disabled={isGeneratingWhatsAppDrafts}
                            className="inline-flex items-center gap-1 h-[26px] px-2.5 rounded-full text-[11px] font-medium text-[#1e40af] bg-white border border-[#bfdbfe] hover:bg-[#eff6ff] disabled:opacity-50 transition-colors cursor-pointer"
                          >
                            <RotateCw
                              className={cn(
                                "w-3 h-3 text-[#2563eb]",
                                isGeneratingWhatsAppDrafts && "animate-spin"
                              )}
                            />
                            <span>{isGeneratingWhatsAppDrafts ? "Drafting..." : "Generate AI Drafts"}</span>
                          </button>
                        </div>

                        <div className="flex items-center gap-2.5">
                          <div className="flex-1 flex items-center bg-white border-[1.5px] border-[#93c5fd] focus-within:border-[#2563eb] rounded-[24px] px-3.5 py-1 gap-2 min-h-[42px] shadow-[0_1px_4px_rgba(37,99,235,0.08)] transition-all">
                            <input
                              type="text"
                              value={whatsappInput}
                              onChange={(e) => setWhatsappInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                  e.preventDefault();
                                  handleSendWhatsApp();
                                }
                              }}
                              placeholder={`Message ${activeContact.name} via WhatsApp...`}
                              className="flex-1 text-[13px] bg-transparent outline-none text-[#111215] placeholder:text-[#8696a0]"
                            />
                            <button
                              type="button"
                              className="text-[#2563eb] hover:text-[#1d4ed8] p-1 cursor-pointer transition-colors"
                              title="Voice input"
                            >
                              <Mic className="w-4 h-4" />
                            </button>
                          </div>

                          <button
                            type="button"
                            onClick={handleSendWhatsApp}
                            disabled={isSendingWhatsApp || !whatsappInput.trim()}
                            className="w-[40px] h-[40px] rounded-full bg-[#2563eb] hover:bg-[#1d4ed8] active:scale-95 text-white flex items-center justify-center shadow-[0_2px_8px_rgba(37,99,235,0.3)] transition-all cursor-pointer shrink-0 disabled:opacity-50"
                          >
                            <Send className="w-4 h-4 ml-0.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* TAB VIEW 3: Brixx Data */}
                  {activeTab === "brixx" && (
                    <div className="flex-1 flex flex-col p-6 space-y-4 bg-white">
                      <div>
                        <h3 className="text-sm font-semibold text-[#111215]">
                          Brixx Tenancy Agreements & Rent Schedules
                        </h3>
                        <p className="text-xs text-[#64748b] mt-0.5">
                          Active contracts and financial guarantees recorded for {activeContact.name}
                        </p>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {activeContact.leases && activeContact.leases.length > 0 ? (
                          activeContact.leases.map((lease) => (
                            <div
                              key={lease.id}
                              className="p-4 rounded-xl border border-[#e2e8f0] bg-[#fafafa] space-y-3"
                            >
                              <div className="flex items-start justify-between">
                                <div>
                                  <h4 className="text-xs font-bold text-[#111215]">{lease.title}</h4>
                                  <p className="text-[11px] font-mono text-[#64748b] mt-0.5">{lease.period}</p>
                                </div>
                                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#f0fdf4] text-[#16a34a] border border-[#bbf7d0] capitalize">
                                  {lease.status.replace("_", " ")}
                                </span>
                              </div>

                              <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-[#e2e8f0]">
                                <div>
                                  <span className="text-[10px] text-[#64748b] uppercase font-bold block">
                                    MONTHLY RENT
                                  </span>
                                  <span className="font-mono font-bold text-[#111215]">{lease.monthlyRent}</span>
                                </div>
                                <div>
                                  <span className="text-[10px] text-[#64748b] uppercase font-bold block">
                                    DEPOSIT HELD
                                  </span>
                                  <span className="font-mono text-[#334155]">{lease.deposit}</span>
                                </div>
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="col-span-2 text-center py-12 text-[#94a3b8] text-xs border border-dashed border-[#e2e8f0] rounded-xl">
                            No lease agreements currently on file.
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* TAB VIEW 4: Tickets */}
                  {activeTab === "tickets" && (
                    <div className="flex-1 flex flex-col p-6 space-y-4 bg-white">
                      {activeContact.name === "Vipin Tyagi" ? (
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
                          <h3 className="text-sm font-semibold text-[#111215]">No active ticket repairs</h3>
                          <p className="text-xs text-[#64748b] max-w-sm mt-1">
                            There are currently no open work orders or contractor dispatches logged for {activeContact.name}.
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </main>

          <AskEstateOSPanel
            currentPageName="Tenants"
            selectedContext={`Tenant Profile: ${activeContact?.name || "All Tenants"} · Phone: ${activeContact?.phone || "N/A"} · Email: ${activeContact?.email || "N/A"}`}
            onActionTriggered={(actionType, payload) => {
              if (actionType === "navigate" && typeof payload === "string") {
                router.push(payload);
              }
            }}
          />
        </div>
      </div>

      <MobileTabBar />

      <ContactFormModal
        isOpen={contactForm.open}
        contact={contactForm.contact}
        onClose={() => setContactForm((f) => ({ ...f, open: false }))}
        onSaved={handleContactSaved}
      />
    </div>
  );
}

export default function TenantsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-zinc-400">Loading tenants...</div>}>
      <TenantsContent />
    </Suspense>
  );
}
