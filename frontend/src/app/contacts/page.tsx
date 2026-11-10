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

function ContactsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const contactParam = searchParams.get("contact");
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  // Left Sidebar Filter state
  const [filterAudience, setFilterAudience] = useState<"all" | "tenant" | "contractor">("all");
  const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Live Contacts loaded from database (strictly real data only)
  const [dbContacts, setDbContacts] = useState<ContactItem[]>([]);
  const [isLoadingContacts, setIsLoadingContacts] = useState<boolean>(true);
  const allAvailableContacts = dbContacts;

  const [selectedContactId, setSelectedContactId] = useState<string>(
    contactParam || ""
  );

  useEffect(() => {
    let isMounted = true;
    async function loadContacts() {
      setIsLoadingContacts(true);
      try {
        const list = await getContactsList(filterAudience);
        if (isMounted && list) {
          setDbContacts(list);
        }
      } finally {
        if (isMounted) setIsLoadingContacts(false);
      }
    }
    loadContacts();
    return () => { isMounted = false; };
  }, [filterAudience]);

  // Profile Card Collapsed/Expanded state (both use #f0f5fb subtle blue)
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

  // Open email thread item inside Gmail-style
  const [openEmailId, setOpenEmailId] = useState<string | null>(null);

  // Sync state if URL changes or database contacts finish loading
  useEffect(() => {
    if (allAvailableContacts.length === 0) return;
    if (contactParam && allAvailableContacts.some((c) => c.id === contactParam)) {
      setSelectedContactId(contactParam);
    } else if (!allAvailableContacts.some((c) => c.id === selectedContactId)) {
      setSelectedContactId(allAvailableContacts[0].id);
    }
  }, [contactParam, allAvailableContacts]);

  // Derived active contact
  const activeContact = useMemo(() => {
    if (allAvailableContacts.length === 0) return null;
    return (
      allAvailableContacts.find((c) => c.id === selectedContactId) ||
      allAvailableContacts[0]
    );
  }, [allAvailableContacts, selectedContactId]);

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

  // Sync state & update SuperAgent context if active contact changes
  useEffect(() => {
    if (activeContact) {
      // Clean slate - only database records will be populated
      setLiveEmails([]);
      setLiveWhatsApp([]);
      setWhatsAppDrafts([]);
      superAgent.setCurrentPageName("Contacts");
      superAgent.setSelectedContext(
        `Contact Profile: ${activeContact.name} (${activeContact.category}) · Role: ${activeContact.unitRole || activeContact.tradeOrRole || "N/A"} · Phone: ${activeContact.phone} · Email: ${activeContact.email}`
      );
    }
  }, [activeContact?.id]);

  // Live background polling for live communications (updates every 8s)
  useEffect(() => {
    let isMounted = true;
    async function fetchLiveComms() {
      if (!activeContact) return;
      try {
        const comms = await getContactCommunications(
          activeContact.id,
          activeContact.email,
          activeContact.phone
        );
        if (comms && isMounted) {
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
          id: res.message_id || `out-${Date.now()}`,
          sender: "Harjot Singh",
          senderEmail: "harjot@estateos.internal",
          subject: replySubject,
          snippet: textToSend.slice(0, 100),
          body: textToSend,
          date: "Today",
          time: res.sent_at || "Just now",
          isUnread: false,
          category: email.category,
          priority: getEmailPriority(email),
        };
        setLiveEmails((prev) => [outboundMsg, ...prev]);
      }
    } catch (err) {
      console.error("Failed to send email reply:", err);
    } finally {
      setIsSendingEmailReply((prev) => ({ ...prev, [email.id]: false }));
    }
  };

  const handleGenerateWhatsAppDrafts = async () => {
    if (!activeContact) return;
    setIsGeneratingWhatsAppDrafts(true);
    try {
      const generated = await generateWhatsAppDrafts(activeContact.id);
      if (generated && generated.length > 0) {
        setWhatsAppDrafts(generated);
      }
    } catch (err) {
      console.error("Failed to generate WhatsApp drafts:", err);
    } finally {
      setIsGeneratingWhatsAppDrafts(false);
    }
  };

  const handleSendWhatsApp = async () => {
    if (!activeContact) return;
    if (!whatsappInput.trim() || isSendingWhatsApp) return;
    const textToSend = whatsappInput.trim();
    setWhatsappInput("");
    setIsSendingWhatsApp(true);

    const now = new Date();
    const timeStr = formatClock(now);
    const optimisticMsg: ContactWhatsAppMessage = {
      id: `temp-${Date.now()}`,
      sender: "owner",
      text: textToSend,
      time: timeStr,
      date: "Today",
      status: "sent",
    };
    setLiveWhatsApp((prev) => [...prev, optimisticMsg]);

    try {
      const res = await sendContactWhatsAppMessage(activeContact.id, textToSend);
      if (res && res.id) {
        setLiveWhatsApp((prev) =>
          prev.map((m) =>
            m.id === optimisticMsg.id
              ? { ...m, id: res.id, status: "delivered" }
              : m
          )
        );
      }
    } catch (err) {
      console.error("Failed to send WhatsApp message:", err);
    } finally {
      setIsSendingWhatsApp(false);
    }
  };

  // Filtered contacts in the left 220px list (re-evaluates when allAvailableContacts loads)
  const filteredContacts = useMemo(() => {
    return allAvailableContacts.filter((contact) => {
      if (filterAudience === "tenant" && contact.category !== "tenant") return false;
      if (filterAudience === "contractor" && contact.category !== "contractor") return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = contact.name.toLowerCase().includes(q);
        const matchesEmail = contact.email.toLowerCase().includes(q);
        const matchesUnit = (contact.unitRole || "").toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesUnit) return false;
      }
      return true;
    });
  }, [allAvailableContacts, filterAudience, searchQuery]);

  // Filtered emails for the active contact
  const filteredEmails = useMemo(() => {
    const listToFilter = liveEmails.length > 0 ? liveEmails : (activeContact?.emails || []);
    return listToFilter.filter((email) => {
      if (onlyUnread && !email.isUnread) return false;

      if (mailCategoryFilter !== "all" && email.category !== mailCategoryFilter) {
        return false;
      }

      const emailPri = getEmailPriority(email);
      if (mailPriorityFilter !== "all" && emailPri !== mailPriorityFilter) {
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
  }, [liveEmails, activeContact, onlyUnread, mailCategoryFilter, mailPriorityFilter, mailSearch]);

  const activeOpenEmail = useMemo(() => {
    if (!openEmailId) return null;
    return filteredEmails.find((e) => e.id === openEmailId) || liveEmails.find((e) => e.id === openEmailId) || null;
  }, [openEmailId, filteredEmails, liveEmails]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0A1B2F] text-[#111215] font-sans antialiased">
      {/* 1. Left Nav (Desktop Sidebar - #0A1B2F dark blue theme) */}
      <Sidebar />

      {/* 2. Content Workspace */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        {/* Top Bar with language switcher and Super Agent */}
        <TopCommandBar pageTitle="Contacts" hideSearch />

        {/* WORKSPACE BODY ROW */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          {/* MAIN CONTAINER (14px rounded corners preserved) */}
          <main
            id="mainContainer"
            className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-row overflow-hidden relative transition-all duration-300"
          >
            {/* PANEL 1: CONTACTS LIST SIDEBAR (220px, subtle neutral #fafafa) */}
            <div
              className={cn(
                "w-[220px] min-w-[220px] shrink-0 flex flex-col border-r border-[#e8e9eb] bg-[#fafafa] overflow-hidden",
                contactParam ? "hidden md:flex" : "flex w-full md:w-[220px]"
              )}
            >
              {/* Header */}
              <div className="p-[14px_12px_10px] shrink-0 border-b border-[#e8e9eb] space-y-2">
                <div className="text-[10.5px] font-bold text-[#64748b] tracking-[0.06em] uppercase">
                  {filterAudience === "all"
                    ? t("All Contacts")
                    : filterAudience === "tenant"
                    ? t("Tenants")
                    : t("Contractors")}
                </div>

                {/* Search Bar with Funnel */}
                <div className="relative flex items-center">
                  <Search className="w-3.5 h-3.5 text-[#94a3b8] absolute left-2.5 pointer-events-none" />
                  <input
                    type="text"
                    placeholder={t("Search...")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full h-[30px] pl-7 pr-8 text-[12px] text-[#111215] bg-white border border-[#d5d9e0] rounded-[6px] outline-none focus:border-[#94a3b8] focus:ring-1 focus:ring-black/5 transition-all placeholder:text-[#94a3b8]"
                  />
                  <button
                    type="button"
                    onClick={() => setIsFilterDropdownOpen((prev) => !prev)}
                    className={cn(
                      "absolute right-0 top-0 bottom-0 w-[30px] flex items-center justify-center text-[#64748b] hover:text-[#1e293b] hover:bg-[#e2e8f0] rounded-r-[6px] transition-colors cursor-pointer",
                      filterAudience !== "all" && "text-[#3b82f6]"
                    )}
                    title={t("Filter contacts", "Contacten filteren")}
                  >
                    <Filter className="w-3.5 h-3.5" />
                  </button>

                  {/* Filter Dropdown */}
                  {isFilterDropdownOpen && (
                    <div className="absolute top-[calc(100%+4px)] left-0 right-0 bg-white border border-[#e5e7eb] rounded-[7px] shadow-[0_8px_24px_rgba(0,0,0,0.1)] z-50 flex flex-col overflow-hidden py-1">
                      <button
                        type="button"
                        onClick={() => {
                          setFilterAudience("all");
                          setIsFilterDropdownOpen(false);
                        }}
                        className={cn(
                          "px-3 py-2 text-[12px] text-left transition-colors cursor-pointer",
                          filterAudience === "all"
                            ? "bg-[#f3f4f6] text-[#111827] font-semibold"
                            : "text-[#6b7280] hover:bg-[#f9fafb] hover:text-[#111827]"
                        )}
                      >
                        {t("All Contacts")}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setFilterAudience("tenant");
                          setIsFilterDropdownOpen(false);
                        }}
                        className={cn(
                          "px-3 py-2 text-[12px] text-left transition-colors cursor-pointer",
                          filterAudience === "tenant"
                            ? "bg-[#f3f4f6] text-[#111827] font-semibold"
                            : "text-[#6b7280] hover:bg-[#f9fafb] hover:text-[#111827]"
                        )}
                      >
                        {t("Tenants")}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setFilterAudience("contractor");
                          setIsFilterDropdownOpen(false);
                        }}
                        className={cn(
                          "px-3 py-2 text-[12px] text-left transition-colors cursor-pointer",
                          filterAudience === "contractor"
                            ? "bg-[#f3f4f6] text-[#111827] font-semibold"
                            : "text-[#6b7280] hover:bg-[#f9fafb] hover:text-[#111827]"
                        )}
                      >
                        {t("Contractors")}
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Contact items scroll */}
              <div className="flex-1 overflow-y-auto py-1.5">
                {isLoadingContacts && allAvailableContacts.length === 0 && (
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
                        router.push(`/contacts?contact=${contact.id}`);
                      }}
                      className={cn(
                        "flex items-center gap-[9px] px-[10px] py-[7px] mx-[6px] my-[1px] rounded-[6px] cursor-pointer transition-colors select-none",
                        isSelected
                          ? "bg-[#e9eaec]"
                          : "hover:bg-[#eceef1]"
                      )}
                    >
                      {/* Avatar */}
                      <div className="w-[26px] h-[26px] rounded-full bg-[#d5d9e0] text-[#374151] font-bold text-[9px] flex items-center justify-center shrink-0 border-[1.5px] border-[#d5d9e0]">
                        {initials}
                      </div>

                      {/* Name & Trade/Unit */}
                      <div className="flex-1 min-w-0 flex flex-col">
                        <span
                          className={cn(
                            "text-[13px] truncate leading-tight",
                            isSelected
                              ? "text-[#0f172a] font-bold"
                              : "text-[#475569] hover:text-[#0f172a]"
                          )}
                        >
                          {contact.name}
                        </span>
                        {contact.tradeOrRole && (
                          <span className="text-[10.5px] text-[#94a3b8] truncate font-medium mt-0.5">
                            {contact.tradeOrRole}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {!isLoadingContacts && filteredContacts.length === 0 && (
                  <div className="text-center py-12 text-[#94a3b8] text-xs">
                    No contacts found in database.
                  </div>
                )}
              </div>
            </div>

            {/* PANEL 2: CONTACT DETAIL */}
            <div
              className={cn(
                "flex-1 flex flex-col overflow-hidden relative",
                !contactParam && "hidden md:flex"
              )}
            >
              {/* Back button on mobile */}
              <div className="md:hidden px-4 py-2 border-b border-[#e8e9eb] bg-[#fafafa]">
                <button
                  type="button"
                  onClick={() => router.push("/contacts")}
                  className="inline-flex items-center gap-1.5 text-xs text-[#475569] font-medium"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  <span>All Contacts</span>
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
                    <p>No contact selected or directory is empty.</p>
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
                        <span
                          className={cn(
                            "inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full capitalize",
                            activeContact.category === "tenant"
                              ? "bg-[#f0fdf4] text-[#16a34a] border border-[#bbf7d0]"
                              : "bg-[#eff6ff] text-[#2563eb] border border-[#bfdbfe]"
                          )}
                        >
                          {activeContact.category}
                        </span>
                      </div>

                      {/* Phone + Email + Agreement Inline Row */}
                      <div className="flex items-center gap-2.5 flex-wrap text-[11.5px] text-[#4b515d]">
                        <a
                          href={`tel:${activeContact.phone}`}
                          className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors"
                        >
                          <Phone className="w-3 h-3 text-[#64748b]" />
                          <span>{activeContact.phone}</span>
                        </a>
                        <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                        <a
                          href={`mailto:${activeContact.email}`}
                          className="inline-flex items-center gap-1 hover:text-[#111215] transition-colors truncate max-w-[220px]"
                        >
                          <Mail className="w-3 h-3 text-[#64748b]" />
                          <span>{activeContact.email}</span>
                        </a>
                        <span className="text-[#94a3b8] text-[9px] select-none">•</span>
                        <div className="inline-flex items-center gap-1">
                          <span className="font-semibold text-[#64748b]">Agreement Duration:</span>
                          <span className="font-medium text-[#111215]">
                            {activeContact.agreementPeriod || "Not on file"}
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
                      {isProfileExpanded ? (
                        <ChevronUp className="w-4 h-4" />
                      ) : (
                        <ChevronDown className="w-4 h-4" />
                      )}
                    </button>
                  </div>

                  {/* Expandable details (Identical #f0f5fb background) */}
                  {isProfileExpanded && (
                    <div className="px-6 py-2 pb-3.5 bg-[#f0f5fb] border-t border-[#e1e7f0] flex flex-col">
                      <div className="flex items-baseline gap-2 py-1 border-b border-[#e4ecf7]">
                        <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                          Property Address:
                        </span>
                        <span className="text-[12px] text-[#111215] font-medium leading-snug">
                          {activeContact.propertyAddress || activeContact.address || "14-22 St. Mark's Square, London EC1A 1BB"}
                        </span>
                      </div>
                      <div className="flex items-baseline gap-2 py-1">
                        <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                          Residential Address:
                        </span>
                        <span className="text-[12px] text-[#111215] font-medium leading-snug">
                          {activeContact.residentialAddress || activeContact.address || "14-22 St. Mark's Square, Unit 12, London EC1A 1BB"}
                        </span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Tabs Bar */}
                <div className="px-6 flex items-center border-b border-[#e5e7eb] bg-white sticky top-0 z-10">
                  <button
                    type="button"
                    onClick={() => setActiveTab("mails")}
                    className={cn(
                      "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                      activeTab === "mails"
                        ? "text-[#111215] font-semibold border-[#121316]"
                        : "text-[#4b515d] border-transparent hover:text-[#111215]"
                    )}
                  >
                    <Mail className="w-3.5 h-3.5" />
                    <span>{t("Mail Inbox", "E-mail Inbox")}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("whatsapp")}
                    className={cn(
                      "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                      activeTab === "whatsapp"
                        ? "text-[#111215] font-semibold border-[#121316]"
                        : "text-[#4b515d] border-transparent hover:text-[#111215]"
                    )}
                  >
                    <MessageSquare className="w-3.5 h-3.5" />
                    <span>{t("WhatsApp")}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("brixx")}
                    className={cn(
                      "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                      activeTab === "brixx"
                        ? "text-[#111215] font-semibold border-[#121316]"
                        : "text-[#4b515d] border-transparent hover:text-[#111215]"
                    )}
                  >
                    <FileText className="w-3.5 h-3.5" />
                    <span>{t("Brixx Data", "Brixx Gegevens")}</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveTab("tickets")}
                    className={cn(
                      "inline-flex items-center gap-1.5 py-[9px] px-[14px] pb-[11px] text-[13px] font-medium border-b-2 transition-all cursor-pointer whitespace-nowrap",
                      activeTab === "tickets"
                        ? "text-[#111215] font-semibold border-[#121316]"
                        : "text-[#4b515d] border-transparent hover:text-[#111215]"
                    )}
                  >
                    <Wrench className="w-3.5 h-3.5" />
                    <span>{t("Ticket Rates", "Reparaties")}</span>
                  </button>
                </div>

                {/* TAB VIEW 1: Mail Inbox */}
                {activeTab === "mails" && (
                  <div className="flex-1 flex flex-col min-h-0">
                    {/* Mail Toolbar */}
                    <div className="px-6 py-2.5 flex items-center justify-between gap-2.5 border-b border-[#e5e7eb] flex-wrap bg-white">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        {/* All Pill */}
                        <button
                          type="button"
                          onClick={() => {
                            setMailCategoryFilter("all");
                            setMailPriorityFilter("all");
                          }}
                          className={cn(
                            "inline-flex items-center h-[27px] px-[11px] text-[11.5px] rounded-full transition-all cursor-pointer whitespace-nowrap",
                            mailCategoryFilter === "all" && mailPriorityFilter === "all"
                              ? "bg-[#121316] text-white font-semibold"
                              : "bg-white text-[#4b515d] border border-[#e5e7eb] hover:bg-[#f8fafc] hover:text-[#111215]"
                          )}
                        >
                          {t("All")}
                        </button>

                        {/* Category Dropdown Pill */}
                        <div className="relative inline-block">
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
                              {["all", "lease", "payment", "maintenance", "complaint", "contractor_update", "admin"].map((cat) => (
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
                                  {cat === "all" ? t("All Categories") : t(cat.replace("_", " "))}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* 4 Priorities Dropdown Pill */}
                        <div className="relative inline-block">
                          <button
                            type="button"
                            onClick={() => {
                              setIsPriorityMenuOpen((prev) => !prev);
                              setIsCategoryMenuOpen(false);
                            }}
                            className={cn(
                              "inline-flex items-center gap-1 h-[27px] px-[11px] text-[11.5px] font-medium rounded-full transition-all cursor-pointer whitespace-nowrap",
                              mailPriorityFilter !== "all"
                                ? "bg-[#0f172a] text-white font-semibold"
                                : "bg-white text-[#4b515d] border border-[#e5e7eb] hover:bg-[#f8fafc] hover:text-[#111215]"
                            )}
                          >
                            <span className="capitalize">{mailPriorityFilter === "all" ? t("Priority", "Prioriteit") : `${t("Priority", "Prioriteit")}: ${t(mailPriorityFilter)}`}</span>
                            <ChevronDown className="w-2.5 h-2.5 opacity-70" />
                          </button>

                          {isPriorityMenuOpen && (
                            <div className="absolute top-[calc(100%+5px)] left-0 min-w-[150px] bg-white border border-[#e2e8f0] rounded-[8px] shadow-[0_8px_24px_rgba(15,23,42,0.1)] p-1 z-50 flex flex-col">
                              <button
                                type="button"
                                onClick={() => {
                                  setMailPriorityFilter("all");
                                  setIsPriorityMenuOpen(false);
                                }}
                                className={cn(
                                  "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left transition-colors cursor-pointer",
                                  mailPriorityFilter === "all"
                                    ? "bg-[#f8fafc] text-[#0f172a] font-semibold"
                                    : "text-[#334155] hover:bg-[#f1f5f9]"
                                )}
                              >
                                {t("All Priorities")}
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setMailPriorityFilter("emergency");
                                  setIsPriorityMenuOpen(false);
                                }}
                                className={cn(
                                  "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left transition-colors cursor-pointer flex items-center gap-1.5",
                                  mailPriorityFilter === "emergency"
                                    ? "bg-red-50 text-red-800 font-semibold"
                                    : "text-red-700 hover:bg-red-50/50"
                                )}
                              >
                                <span className="w-2 h-2 rounded-full bg-red-600" />
                                <span>{t("Emergency")}</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setMailPriorityFilter("high");
                                  setIsPriorityMenuOpen(false);
                                }}
                                className={cn(
                                  "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left transition-colors cursor-pointer flex items-center gap-1.5",
                                  mailPriorityFilter === "high"
                                    ? "bg-amber-50 text-amber-800 font-semibold"
                                    : "text-amber-700 hover:bg-amber-50/50"
                                )}
                              >
                                <span className="w-2 h-2 rounded-full bg-amber-500" />
                                <span>{t("High")}</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setMailPriorityFilter("normal");
                                  setIsPriorityMenuOpen(false);
                                }}
                                className={cn(
                                  "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left transition-colors cursor-pointer flex items-center gap-1.5",
                                  mailPriorityFilter === "normal"
                                    ? "bg-blue-50 text-blue-800 font-semibold"
                                    : "text-blue-700 hover:bg-blue-50/50"
                                )}
                              >
                                <span className="w-2 h-2 rounded-full bg-blue-500" />
                                <span>Normal</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setMailPriorityFilter("low");
                                  setIsPriorityMenuOpen(false);
                                }}
                                className={cn(
                                  "px-2.5 py-1.5 text-[11.5px] rounded-[5px] text-left transition-colors cursor-pointer flex items-center gap-1.5",
                                  mailPriorityFilter === "low"
                                    ? "bg-zinc-100 text-zinc-900 font-semibold"
                                    : "text-zinc-600 hover:bg-zinc-100/60"
                                )}
                              >
                                <span className="w-2 h-2 rounded-full bg-zinc-400" />
                                <span>Low</span>
                              </button>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Right: Unread Toggle Switch + Search */}
                      <div className="flex items-center gap-3">
                        <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={onlyUnread}
                            onChange={(e) => setOnlyUnread(e.target.checked)}
                            className="hidden"
                          />
                          <span
                            className={cn(
                              "w-[28px] h-[16px] rounded-full relative transition-colors shrink-0",
                              onlyUnread ? "bg-[#111111]" : "bg-[#d1d5db]"
                            )}
                          >
                            <span
                              className={cn(
                                "absolute top-[2px] left-[2px] w-[12px] h-[12px] bg-white rounded-full transition-transform",
                                onlyUnread && "translate-x-[12px]"
                              )}
                            />
                          </span>
                          <span className="text-[11.5px] font-medium text-[#4b515d]">Unread</span>
                        </label>

                        {/* Search mail */}
                        <div className="relative flex items-center">
                          <Search className="w-3.5 h-3.5 text-[#8b929e] absolute left-2.5 pointer-events-none" />
                          <input
                            type="text"
                            placeholder="Search mail..."
                            value={mailSearch}
                            onChange={(e) => setMailSearch(e.target.value)}
                            className="w-[160px] focus:w-[200px] transition-all h-[26px] pl-[30px] pr-2.5 text-[12px] text-[#111215] bg-white border border-[#e5e7eb] rounded-full outline-none placeholder:text-[#8b929e]"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Email Thread Opened View (Like Gmail: full thread viewer inside) */}
                    {activeOpenEmail ? (
                      <div className="flex-1 flex flex-col overflow-y-auto bg-white p-6 space-y-4">
                        {/* Top bar with back to inbox */}
                        <div className="flex items-center justify-between border-b border-[#e5e7eb] pb-3">
                          <button
                            type="button"
                            onClick={() => setOpenEmailId(null)}
                            className="inline-flex items-center gap-1.5 text-xs text-[#475569] hover:text-[#0f172a] font-medium cursor-pointer"
                          >
                            <ArrowLeft className="w-3.5 h-3.5" />
                            <span>Back to email list</span>
                          </button>

                          <div className="flex items-center gap-2">
                            {activeOpenEmail.category && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#f1f5f9] text-[#475569] border border-[#e2e8f0] uppercase tracking-wider">
                                {activeOpenEmail.category.replace("_", " ")}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Thread Subject Title */}
                        <h2 className="text-base sm:text-lg font-bold text-[#111215] tracking-tight">
                          {activeOpenEmail.subject}
                        </h2>

                        {/* Sender info */}
                        <div className="flex items-start justify-between text-xs pt-1 border-b border-[#f3f4f6] pb-3">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-full bg-[#111215] text-white font-bold text-xs flex items-center justify-center shrink-0">
                              {getInitials(activeOpenEmail.sender)}
                            </div>
                            <div>
                              <div className="font-semibold text-[#111215] text-xs">
                                {activeOpenEmail.sender}
                              </div>
                              <div className="text-[#64748b] text-[11px] font-mono">
                                &lt;{activeOpenEmail.senderEmail}&gt; · to me
                              </div>
                            </div>
                          </div>
                          <span className="text-[11px] text-[#8b929e] font-mono">
                            {activeOpenEmail.date} at {activeOpenEmail.time}
                          </span>
                        </div>

                        {/* Message Body */}
                        <div className="text-[13px] text-[#334155] leading-relaxed whitespace-pre-line py-2">
                          {activeOpenEmail.body}
                        </div>

                        {/* Attachments */}
                        {activeOpenEmail.hasAttachments && (
                          <div className="py-2 flex items-center gap-2">
                            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[#cbd5e1] bg-[#f8fafc] text-xs text-[#334155]">
                              <Paperclip className="w-3.5 h-3.5 text-[#64748b]" />
                              <span>lease_addendum_2024.pdf</span>
                              <span className="text-[#94a3b8] text-[10px]">(2.4 MB)</span>
                            </div>
                          </div>
                        )}

                        {/* Proposer Agent AI Draft Reply Box */}
                        <div className="mt-4 pt-4 border-t border-[#e2e8f0] space-y-3 bg-[#f8fafc] p-4 rounded-xl border">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5 text-xs font-semibold text-[#111215]">
                              <Sparkles className="w-3.5 h-3.5 text-[#1a73e8]" />
                              <span>AI Draft Reply (Proposer Agent)</span>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleGenerateEmailDrafts(activeOpenEmail)}
                              disabled={isGeneratingEmailDraft[activeOpenEmail.id]}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium text-[#1e293b] bg-white border border-[#cbd5e1] hover:bg-[#f1f5f9] disabled:opacity-50 transition-colors cursor-pointer shadow-2xs"
                            >
                              <RotateCw
                                className={cn(
                                  "w-3 h-3 text-[#64748b]",
                                  isGeneratingEmailDraft[activeOpenEmail.id] && "animate-spin text-[#1a73e8]"
                                )}
                              />
                              <span>
                                {isGeneratingEmailDraft[activeOpenEmail.id] ? "Drafting..." : "Generate AI Draft"}
                              </span>
                            </button>
                          </div>

                          {/* 3 Selectable Draft Variant Pills */}
                          {activeOpenEmail.draftVariants && activeOpenEmail.draftVariants.length > 0 ? (
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {activeOpenEmail.draftVariants.map((variant, idx) => {
                                const isSelected =
                                  (emailDraftChoices[activeOpenEmail.id] || activeOpenEmail.draftVariants![0].id) === variant.id;
                                return (
                                  <button
                                    key={variant.id || idx}
                                    type="button"
                                    onClick={() => handleSelectEmailDraft(activeOpenEmail.id, variant)}
                                    className={cn(
                                      "px-2.5 py-1 rounded-full text-[11px] font-medium transition-all cursor-pointer border",
                                      isSelected
                                        ? "bg-[#111215] text-white border-[#111215] shadow-2xs"
                                        : "bg-white border-[#cbd5e1] text-[#475569] hover:bg-[#f1f5f9]"
                                    )}
                                  >
                                    {variant.label || `Option ${idx + 1}`}
                                  </button>
                                );
                              })}
                            </div>
                          ) : null}

                          {/* Editable Textarea */}
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
                            placeholder="Type or customize your email reply to this thread..."
                            className="w-full p-2.5 rounded-lg text-xs leading-relaxed bg-white border border-[#cbd5e1] text-[#111215] placeholder:text-[#94a3b8] focus:outline-none focus:ring-1 focus:ring-[#1a73e8] resize-y"
                          />

                          {/* Send Footer */}
                          <div className="flex items-center justify-between gap-3 pt-1 flex-wrap">
                            <span className="text-[11px] text-[#64748b]">
                              Replying directly to: {activeOpenEmail.subject.startsWith("Re:") ? activeOpenEmail.subject : `Re: ${activeOpenEmail.subject}`}
                            </span>

                            <div className="flex items-center gap-2">
                              {sentEmailSuccess[activeOpenEmail.id] && (
                                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                                  <CheckCircle2 className="w-3.5 h-3.5" />
                                  Sent via Mail
                                </span>
                              )}
                              <button
                                type="button"
                                onClick={() => handleSendEmailReply(activeOpenEmail)}
                                disabled={
                                  isSendingEmailReply[activeOpenEmail.id] ||
                                  !(emailDraftCustomText[activeOpenEmail.id] || activeOpenEmail.draftVariants?.[0]?.body)
                                }
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold text-white bg-[#111215] hover:bg-black disabled:opacity-50 transition-colors cursor-pointer shadow-2xs"
                              >
                                <Send className="w-3.5 h-3.5" />
                                <span>{isSendingEmailReply[activeOpenEmail.id] ? "Sending..." : "Send via Mail"}</span>
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* Flat Mail List (Stars removed, priority shown directly, opens thread inside on click) */
                      <div className="flex-1 overflow-y-auto divide-y divide-[#f3f4f6]">
                        {filteredEmails.map((email) => {
                          const priority = getEmailPriority(email);

                          return (
                            <div
                              key={email.id}
                              onClick={() => setOpenEmailId(email.id)}
                              className={cn(
                                "flex items-center justify-between gap-3 px-7 py-2.5 min-h-[44px] cursor-pointer transition-colors select-none",
                                email.isUnread
                                  ? "bg-[#fafbff] hover:bg-[#f3f5fb]"
                                  : "bg-white hover:bg-[#f9fafb]"
                              )}
                            >
                              {/* Left: Category Badge + Subject */}
                              <div className="flex-1 min-w-0 flex items-center gap-2.5">
                                {email.category && (
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-[#f1f5f9] text-[#475569] border border-[#e2e8f0] uppercase tracking-wider shrink-0">
                                    {email.category.replace("_", " ")}
                                  </span>
                                )}

                                <span
                                  className={cn(
                                    "text-[13px] truncate",
                                    email.isUnread
                                      ? "text-[#111215] font-semibold"
                                      : "text-[#4b515d]"
                                  )}
                                >
                                  {email.subject}
                                </span>
                                <span className="text-[#94a3b8] text-[12px] truncate hidden md:inline font-normal">
                                  — {email.snippet}
                                </span>
                              </div>

                              {/* Right: Reply Pill + Timestamp */}
                              <div className="flex items-center gap-2.5 shrink-0">
                                {email.hasAttachments && (
                                  <Paperclip className="w-3.5 h-3.5 text-[#94a3b8]" />
                                )}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setOpenEmailId(email.id);
                                  }}
                                  className="inline-flex items-center gap-1 h-[24px] px-2.5 rounded-full text-[11px] font-medium border border-[#e5e7eb] text-[#8b929e] hover:text-[#111215] hover:bg-[#f1f5f9] transition-colors cursor-pointer"
                                >
                                  <CornerDownRight className="w-3 h-3" />
                                  <span>Reply</span>
                                </button>

                                <span className="text-[11px] text-[#8b929e] font-mono min-w-[36px] text-right">
                                  {email.time}
                                </span>
                              </div>
                            </div>
                          );
                        })}

                        {filteredEmails.length === 0 && (
                          <div className="text-center py-16 text-[#94a3b8] text-xs">
                            No emails found in database for this contact.
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* TAB VIEW 2: WhatsApp Tab with full WA theme & AI Blue Chat Bar */}
                {activeTab === "whatsapp" && (
                  <div className="flex-1 flex flex-col min-h-[500px] bg-[#e5ddd5] overflow-hidden">
                    {/* Messages Area with Tiled WA Theme */}
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
                          No previous WhatsApp messages recorded in database for this contact.
                        </div>
                      )}
                    </div>

                    {/* WhatsApp Chat Bar — Subtle AI Blue theme */}
                    <div className="p-3 bg-[#f0f7ff] border-t border-[#bfdbfe] flex flex-col gap-2 shrink-0">
                      {/* AI Draft Pills */}
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

                      {/* Chat Input Pill + Mic + Circular Send Button */}
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

                        {/* Send Button — 40px Circle Primary Blue */}
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

                {/* TAB VIEW 4: Ticket Rates (Maintenance) */}
                {activeTab === "tickets" && (
                  <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-white">
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
          </main>

          {/* Consistent Global Super Agent Panel across all pages */}
          <AskEstateOSPanel
            currentPageName="Contacts"
            selectedContext={`Contact Profile: ${activeContact?.name || "All Contacts"} (${activeContact?.category || "tenant"}) · Phone: ${activeContact?.phone || "N/A"} · Email: ${activeContact?.email || "N/A"}`}
            onActionTriggered={(actionType, payload) => {
              if (actionType === "navigate" && typeof payload === "string") {
                router.push(payload);
              }
            }}
          />
        </div>
      </div>

      {/* Mobile Tab Bar */}
      <MobileTabBar />
    </div>
  );
}

export default function ContactsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-zinc-400">Loading contacts...</div>}>
      <ContactsContent />
    </Suspense>
  );
}
