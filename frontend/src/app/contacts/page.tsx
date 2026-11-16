"use client";

import React, { useState, useMemo, useEffect, useRef, Suspense } from "react";
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
  MicOff,
  Filter,
  Phone,
  Plus,
  Pencil,
  Info,
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
import { ContactFormModal } from "@/components/contacts/ContactFormModal";
import type { SavedContact } from "@/lib/contactsWriteApi";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";

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
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-tight bg-white text-[var(--ink)] border border-[var(--line)] shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
          Emergency
        </span>
      );
    case "high":
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-tight bg-white text-[var(--ink)] border border-[var(--line)] shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          High
        </span>
      );
    case "normal":
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-tight bg-white text-[var(--ink-2)] border border-[var(--line)] shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-[#2563eb]" />
          Normal
        </span>
      );
    case "low":
    default:
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-tight bg-white text-[var(--ink-3)] border border-[var(--line)] shrink-0">
          <span className="w-1.5 h-1.5 rounded-full bg-zinc-400" />
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
  const [contactForm, setContactForm] = useState<{ open: boolean; contact: ContactItem | null }>({
    open: false,
    contact: null,
  });
  const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Live Contacts loaded from database (strictly real data only)
  const [dbContacts, setDbContacts] = useState<ContactItem[]>([]);
  const [isLoadingContacts, setIsLoadingContacts] = useState<boolean>(true);
  const allAvailableContacts = dbContacts;

  // A contact just added or classified: show it in the list (replacing the old row) and open it.
  const handleContactSaved = (saved: SavedContact) => {
    setDbContacts((prev) => {
      const rest = prev.filter((c) => c.id !== saved.id);
      return [...rest, saved].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    });
    setFilterAudience("all");
    setSelectedContactId(saved.id);
    setOpenEmailId(null);
    router.push(`/contacts?contact=${saved.id}`);
  };

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

  // Profile Card Collapsed/Expanded state (null = collapsed on <md mobile, expanded on >=md desktop)
  const [isProfileExpanded, setIsProfileExpanded] = useState<boolean | null>(null);
  const [mobileInfoPref, setMobileInfoPref] = useState<{ contactId: string; expanded: boolean }>({
    contactId: "",
    expanded: true,
  });
  const whatsappTextareaRef = useRef<HTMLTextAreaElement>(null);

  const handleToggleProfileExpanded = () => {
    setIsProfileExpanded((prev) => {
      if (prev === null) {
        return typeof window !== "undefined" && window.innerWidth >= 768 ? false : true;
      }
      return !prev;
    });
  };

  // Detail pane tabs: "mails" | "whatsapp" | "brixx" | "tickets"
  const [activeTab, setActiveTab] = useState<"mails" | "whatsapp" | "brixx" | "tickets">("mails");

  const handleSelectTab = (tab: "mails" | "whatsapp" | "brixx" | "tickets", contactId?: string) => {
    setActiveTab(tab);
    if (contactId) {
      setMobileInfoPref({ contactId, expanded: false });
    }
  };

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

  const isMobileInfoExpanded =
    activeContact && mobileInfoPref.contactId === activeContact.id ? mobileInfoPref.expanded : true;

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

  // Voice-to-text dictation state (shared between Email and WhatsApp composers)
  const [voiceTarget, setVoiceTarget] = useState<"whatsapp" | "email" | null>(null);
  const voiceTargetRef = useRef<"whatsapp" | "email" | null>(null);
  const voiceEmailIdRef = useRef<string | null>(null);

  const {
    isListening,
    speechLang,
    setSpeechLang,
    startListening,
    stopListening,
  } = useVoiceInput({
    initialLang: "nl",
    onTranscript: (liveText) => {
      if (voiceTargetRef.current === "whatsapp") {
        setWhatsappInput(liveText);
      } else if (voiceTargetRef.current === "email" && voiceEmailIdRef.current) {
        const targetEmailId = voiceEmailIdRef.current;
        setEmailDraftCustomText((prev) => ({
          ...prev,
          [targetEmailId]: liveText,
        }));
      }
    },
  });

  const activeVoiceTarget = isListening ? voiceTarget : null;
  const isListeningRef = useRef(false);
  const stopListeningRef = useRef(stopListening);

  useEffect(() => {
    isListeningRef.current = isListening;
    stopListeningRef.current = stopListening;
    if (!isListening) {
      voiceTargetRef.current = null;
      voiceEmailIdRef.current = null;
    }
  }, [isListening, stopListening]);

  useEffect(() => {
    voiceTargetRef.current = null;
    voiceEmailIdRef.current = null;
    if (isListeningRef.current) {
      stopListeningRef.current();
    }
  }, [activeTab, activeContact?.id, openEmailId]);

  const handleToggleDictation = (
    target: "whatsapp" | "email",
    existingText: string,
    emailId?: string
  ) => {
    if (isListening && voiceTargetRef.current === target) {
      stopListening();
      voiceTargetRef.current = null;
      voiceEmailIdRef.current = null;
      setVoiceTarget(null);
      return;
    }
    if (isListening) {
      stopListening();
    }
    voiceTargetRef.current = target;
    voiceEmailIdRef.current = target === "email" ? emailId ?? null : null;
    setVoiceTarget(target);
    startListening(existingText);
  };

  const handleToggleSpeechLang = () => {
    if (isListening) {
      stopListening();
      voiceTargetRef.current = null;
      voiceEmailIdRef.current = null;
      setVoiceTarget(null);
    }
    setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"));
  };

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

  // Auto-grow WhatsApp typing box as user types or selects an AI draft
  useEffect(() => {
    const el = whatsappTextareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 96)}px`;
  }, [whatsappInput, activeTab]);

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
    if (isListening) {
      stopListening();
    }
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
    if (isListening) {
      stopListening();
    }
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

  // Filtered contacts in the left 220px list (strictly portfolio contacts: Tenants & Contractors)
  const filteredContacts = useMemo(() => {
    return allAvailableContacts.filter((contact) => {
      // Must be a tenant or contractor
      if (contact.category !== "tenant" && contact.category !== "contractor") return false;
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
    <div className="flex h-dvh w-full overflow-hidden bg-[#0A1B2F] text-[#111215] font-sans antialiased">
      {/* 1. Left Nav (Desktop Sidebar - #0A1B2F dark blue theme) */}
      <Sidebar />

      {/* 2. Content Workspace */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        {/* Top Bar with language switcher and Super Agent */}
        <TopCommandBar pageTitle="Contacts" hideSearch />

        {/* WORKSPACE BODY ROW */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          {/* MAIN CONTAINER (14px rounded corners preserved on desktop, full-bleed on mobile) */}
          <main
            id="mainContainer"
            className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#27272a] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-row overflow-hidden relative transition-all duration-300"
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
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10.5px] font-bold text-[#64748b] tracking-[0.06em] uppercase">
                    {filterAudience === "all"
                      ? t("All Contacts")
                      : filterAudience === "tenant"
                      ? t("Tenants")
                      : filterAudience === "contractor"
                      ? t("Contractors")
                      : t("Other")}
                  </div>
                  <button
                    type="button"
                    onClick={() => setContactForm({ open: true, contact: null })}
                    title={t("contacts.add_contact", "Add contact")}
                    aria-label={t("contacts.add_contact", "Add contact")}
                    className="inline-flex items-center gap-1 h-[22px] px-2 rounded-[6px] bg-[#111215] text-white text-[10.5px] font-semibold hover:bg-[#27272a] transition-colors cursor-pointer"
                  >
                    <Plus className="w-3 h-3" />
                    <span>{t("common.add", "Add")}</span>
                  </button>
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
              <div className="flex-1 overflow-y-auto py-1.5 pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-1.5">
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
                        setMobileInfoPref({ contactId: contact.id, expanded: true });
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
                    No contacts yet. People who write to you by email or WhatsApp appear here, or add one with the Add button.
                  </div>
                )}
              </div>
            </div>

            {/* PANEL 2: CONTACT DETAIL */}
            <div
              className={cn(
                "flex-1 flex flex-col min-h-0 overflow-hidden relative pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0",
                !contactParam && "hidden md:flex"
              )}
            >
              {/* Compact sticky bar on mobile: Back + Name + Info dropdown */}
              <div className="md:hidden flex items-center justify-between gap-2 px-3 py-2 border-b border-[#e8e9eb] bg-[#fafafa] shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    type="button"
                    onClick={() => router.push("/contacts")}
                    className="inline-flex items-center gap-1 text-xs text-[#475569] font-medium shrink-0 py-0.5 pr-1"
                    aria-label="Back to All Contacts"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    {!activeContact && <span>All Contacts</span>}
                  </button>
                  {activeContact && (
                    <>
                      <div className="w-7 h-7 rounded-full bg-[#27272a] text-white font-bold text-[10px] flex items-center justify-center shrink-0">
                        {getInitials(activeContact.name)}
                      </div>
                      <span className="text-[13px] font-bold text-[#111215] truncate">
                        {activeContact.name}
                      </span>
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[9.5px] font-semibold rounded-full capitalize bg-white text-[#1e293b] border border-[#e2e8f0] shrink-0">
                        <span
                          className={cn(
                            "w-1.5 h-1.5 rounded-full",
                            activeContact.category === "tenant"
                              ? "bg-emerald-500"
                              : activeContact.category === "contractor"
                              ? "bg-[#2563eb]"
                              : "bg-slate-400"
                          )}
                        />
                        {activeContact.category}
                      </span>
                    </>
                  )}
                </div>
                {activeContact && (
                  <button
                    type="button"
                    onClick={() =>
                      setMobileInfoPref({
                        contactId: activeContact.id,
                        expanded: !isMobileInfoExpanded,
                      })
                    }
                    className={cn(
                      "inline-flex items-center gap-1 h-[26px] px-2.5 rounded-full text-[11px] font-semibold border transition-colors shrink-0 cursor-pointer",
                      isMobileInfoExpanded
                        ? "bg-[#e0edff] text-[#1d4ed8] border-[#bfdbfe]"
                        : "bg-white text-[#475569] border-[#d5d9e0]"
                    )}
                    aria-expanded={isMobileInfoExpanded}
                  >
                    <Info className="w-3 h-3" />
                    <span>{isMobileInfoExpanded ? "Hide info" : "Info"}</span>
                    {isMobileInfoExpanded ? (
                      <ChevronUp className="w-3 h-3" />
                    ) : (
                      <ChevronDown className="w-3 h-3" />
                    )}
                  </button>
                )}
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
              <div
                className={cn(
                  "flex-1 flex flex-col min-h-0",
                  activeTab === "whatsapp" ? "overflow-hidden" : "overflow-y-auto"
                )}
              >
                {/* Profile Card (desktop always shown; on mobile shown first or via Info dropdown) */}
                <div
                  className={cn(
                    "bg-[#f0f5fb] border-b border-[#e1e7f0] transition-colors shrink-0",
                    !isMobileInfoExpanded && "hidden md:block"
                  )}
                >
                  <div className="flex items-center gap-3 px-3.5 py-2.5 sm:px-6 sm:py-3.5 bg-[#f0f5fb]">
                    {/* 44px Avatar (desktop) */}
                    <div className="hidden md:flex w-[44px] h-[44px] rounded-full bg-[#27272a] text-white font-bold text-[15px] items-center justify-center shrink-0 border-2 border-[#d5d9e0]">
                      {getInitials(activeContact.name)}
                    </div>

                    {/* Summary */}
                    <div className="flex-1 min-w-0 flex flex-col gap-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="hidden md:inline text-[14px] font-bold text-[#111215] tracking-[-0.01em]">
                          {activeContact.name}
                        </span>
                        <span className="hidden md:inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[10.5px] font-semibold rounded-full capitalize bg-white text-[#1e293b] border border-[#e2e8f0]">
                          <span
                            className={cn(
                              "w-1.5 h-1.5 rounded-full",
                              activeContact.category === "tenant"
                                ? "bg-emerald-500"
                                : activeContact.category === "contractor"
                                ? "bg-[#2563eb]"
                                : "bg-slate-400"
                            )}
                          />
                          {activeContact.category}
                        </span>
                        {(activeContact as SavedContact).unclassified && (
                          <span className="inline-flex items-center gap-1.5 text-[10.5px] text-[#475569] bg-white border border-[#e2e8f0] rounded-full px-2.5 py-0.5 font-medium">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            From messages, not classified yet
                          </span>
                        )}
                        {(activeContact as SavedContact).source === "directory" && (
                          <button
                            type="button"
                            onClick={() => setContactForm({ open: true, contact: activeContact })}
                            className="inline-flex items-center gap-1 text-[10.5px] font-semibold text-[#2563eb] hover:text-[#1d4ed8] cursor-pointer"
                          >
                            <Pencil className="w-3 h-3" />
                            {(activeContact as SavedContact).unclassified ? "Name & classify" : "Edit"}
                          </button>
                        )}
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
                          <span className="font-semibold text-[#64748b]">{t("Agreement Duration:")}</span>
                          <span className="font-medium text-[#111215]">
                            {activeContact.agreementPeriod || t("Not on file")}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Chevron Toggle Button (Desktop) */}
                    <button
                      type="button"
                      onClick={handleToggleProfileExpanded}
                      className="hidden md:flex w-7 h-7 rounded-full bg-white border border-[#d5d9e0] text-[#64748b] items-center justify-center hover:bg-[#f8fafc] hover:text-[#0f172a] transition-all cursor-pointer shrink-0"
                      title={isProfileExpanded === false ? "Expand address details" : "Collapse address details"}
                    >
                      {isProfileExpanded === null || isProfileExpanded ? (
                        <ChevronUp className="w-4 h-4" />
                      ) : (
                        <ChevronDown className="w-4 h-4" />
                      )}
                    </button>
                  </div>

                  {/* Expandable address details (always shown when mobile Info is open; toggled by chevron on desktop) */}
                  <div
                    className={cn(
                      "px-3.5 sm:px-6 py-2 pb-3 bg-[#f0f5fb] border-t border-[#e1e7f0] flex-col",
                      isProfileExpanded === false ? "flex md:hidden" : "flex"
                    )}
                  >
                      <div className="flex items-baseline gap-2 py-1 border-b border-[#e4ecf7]">
                        <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                          {t("Property Address:")}
                        </span>
                        <span className="text-[12px] text-[#111215] font-medium leading-snug">
                          {activeContact.propertyAddress || activeContact.address || "14-22 St. Mark's Square, London EC1A 1BB"}
                        </span>
                      </div>
                      <div className="flex items-baseline gap-2 py-1">
                        <span className="font-semibold text-[11.5px] text-[#64748b] min-w-[140px] shrink-0">
                          {t("Residential Address:")}
                        </span>
                        <span className="text-[12px] text-[#111215] font-medium leading-snug">
                          {activeContact.residentialAddress || activeContact.address || "14-22 St. Mark's Square, Unit 12, London EC1A 1BB"}
                        </span>
                      </div>
                    </div>
                </div>

                {/* Tabs Bar */}
                <div className="px-3 sm:px-6 flex items-center border-b border-[#e5e7eb] bg-white sticky top-0 z-10 overflow-x-auto no-scrollbar shrink-0">
                  <button
                    type="button"
                    onClick={() => handleSelectTab("mails", activeContact.id)}
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
                    onClick={() => handleSelectTab("whatsapp", activeContact.id)}
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
                    onClick={() => handleSelectTab("brixx", activeContact.id)}
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
                    onClick={() => handleSelectTab("tickets", activeContact.id)}
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
                    <div className="px-3.5 sm:px-6 py-2.5 flex items-center justify-between gap-2.5 border-b border-[#e5e7eb] flex-wrap bg-white">
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
                                <span>{t("Normal")}</span>
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
                                <span>{t("Low")}</span>
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
                          <span className="text-[11.5px] font-medium text-[#4b515d]">{t("Unread")}</span>
                        </label>

                        {/* Search mail */}
                        <div className="relative flex items-center">
                          <Search className="w-3.5 h-3.5 text-[#8b929e] absolute left-2.5 pointer-events-none" />
                          <input
                            type="text"
                            placeholder={t("Search in emails...")}
                            value={mailSearch}
                            onChange={(e) => setMailSearch(e.target.value)}
                            className="w-[160px] focus:w-[200px] transition-all h-[26px] pl-[30px] pr-2.5 text-[12px] text-[#111215] bg-white border border-[#e5e7eb] rounded-full outline-none placeholder:text-[#8b929e]"
                          />
                        </div>
                      </div>
                    </div>

                    {/* Email Thread Opened View (Like Gmail: full thread viewer inside) */}
                    {activeOpenEmail ? (
                      <div className="flex-1 flex flex-col overflow-y-auto bg-white p-3.5 sm:p-6 pb-8 space-y-4">
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

                          {/* Send & Voice Dictation Footer */}
                          <div className="flex items-center justify-between gap-3 pt-1 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap">
                              <button
                                type="button"
                                onClick={() => {
                                  const currentEmailBody =
                                    emailDraftCustomText[activeOpenEmail.id] !== undefined
                                      ? emailDraftCustomText[activeOpenEmail.id]
                                      : activeOpenEmail.draftVariants?.[0]?.body || "";
                                  handleToggleDictation("email", currentEmailBody, activeOpenEmail.id);
                                }}
                                className={cn(
                                  "px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 shrink-0 border select-none",
                                  activeVoiceTarget === "email"
                                    ? "bg-cyan-500 text-black border-cyan-400 shadow-[0_0_12px_rgba(0,229,255,0.6)] animate-pulse font-semibold ring-2 ring-cyan-300"
                                    : "bg-white hover:bg-[#f1f5f9] text-[#334155] hover:text-[#111215] border-[#cbd5e1]"
                                )}
                                title={
                                  activeVoiceTarget === "email"
                                    ? "Listening... click to stop"
                                    : `Voice dictation (${speechLang === "nl" ? "Dutch" : "English"})`
                                }
                                aria-label="Voice dictation for email reply"
                              >
                                {activeVoiceTarget === "email" ? (
                                  <MicOff className="w-3.5 h-3.5 text-black stroke-[2.5]" />
                                ) : (
                                  <Mic className="w-3.5 h-3.5 text-[#1a73e8] stroke-[2]" />
                                )}
                                <span>{activeVoiceTarget === "email" ? "Listening..." : "Dictate"}</span>
                              </button>

                              <button
                                type="button"
                                onClick={handleToggleSpeechLang}
                                className={cn(
                                  "text-[10.5px] font-bold px-2 py-0.5 rounded-full border transition-all cursor-pointer flex items-center gap-1 select-none",
                                  speechLang === "nl"
                                    ? "bg-amber-500/15 text-amber-700 border-amber-500/30 hover:bg-amber-500/25"
                                    : "bg-blue-500/15 text-blue-700 border-blue-500/30 hover:bg-blue-500/25"
                                )}
                                title={
                                  speechLang === "nl"
                                    ? "Voice language: Nederlands (click to switch to English)"
                                    : "Voice language: English (click to switch to Nederlands)"
                                }
                              >
                                {speechLang === "nl" ? <FlagNL className="w-3.5 h-2.5" /> : <FlagUK className="w-3.5 h-2.5" />}
                                <span>{speechLang === "nl" ? "NL" : "EN"}</span>
                              </button>

                              {activeVoiceTarget === "email" ? (
                                <span className="text-[11px] text-cyan-700 font-medium animate-pulse flex items-center gap-1.5 pl-1">
                                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-ping inline-block" />
                                  <span>
                                    {speechLang === "nl"
                                      ? "Luisteren (Nederlands)..."
                                      : "Listening (English)..."}
                                  </span>
                                </span>
                              ) : (
                                <span className="text-[11px] text-[#64748b]">
                                  Replying directly to: {activeOpenEmail.subject.startsWith("Re:") ? activeOpenEmail.subject : `Re: ${activeOpenEmail.subject}`}
                                </span>
                              )}
                            </div>

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
                              onClick={() => {
                                setOpenEmailId(email.id);
                                setMobileInfoPref({ contactId: activeContact.id, expanded: false });
                              }}
                              className={cn(
                                "flex items-center justify-between gap-3 px-3.5 sm:px-7 py-2.5 min-h-[44px] cursor-pointer transition-colors select-none",
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
                                    setMobileInfoPref({ contactId: activeContact.id, expanded: false });
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
                  <div className="flex-1 flex flex-col min-h-0 md:min-h-[420px] bg-[#e5ddd5] overflow-hidden">
                    {/* Messages Area with Tiled WA Theme */}
                    <div className="flex-1 min-h-0 overflow-y-auto p-3.5 sm:p-5 flex flex-col gap-2.5">
                      {liveWhatsApp && liveWhatsApp.length > 0 ? (
                        liveWhatsApp.map((msg) => {
                          const isTenant = msg.sender === "tenant";

                          return (
                            <div
                              key={msg.id}
                              className={cn(
                                "flex flex-col max-w-[82%] sm:max-w-[72%]",
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
                        <div className="text-center py-12 sm:py-20 text-[#64748b] text-xs">
                          No previous WhatsApp messages recorded in database for this contact.
                        </div>
                      )}
                    </div>

                    {/* WhatsApp Chat Bar — Subtle AI Blue theme */}
                    <div className="p-2.5 sm:p-3 bg-[#f0f7ff] border-t border-[#bfdbfe] flex flex-col gap-2 shrink-0">
                      {/* AI Draft Pills */}
                      <div className="flex items-center justify-between gap-2 px-0.5">
                        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar min-w-0 flex-1 py-0.5">
                          <span className="text-[11px] font-semibold text-[#1d4ed8] flex items-center gap-1 shrink-0">
                            <Sparkles className="w-3 h-3 text-[#2563eb] animate-wa-sparkle" />
                            AI Draft:
                          </span>
                          {whatsAppDrafts.length > 0 ? (
                            whatsAppDrafts.map((d, i) => (
                              <button
                                key={d.id || i}
                                type="button"
                                onClick={() => setWhatsappInput(d.body)}
                                className="inline-flex items-center gap-1 h-[26px] px-2.5 rounded-full text-[11px] font-semibold bg-[#eff6ff] hover:bg-[#dbeafe] border border-[#bfdbfe] text-[#1d4ed8] transition-all cursor-pointer shadow-2xs whitespace-nowrap shrink-0"
                                title={d.body}
                              >
                                <span>{d.label || `Draft ${i + 1}`}</span>
                              </button>
                            ))
                          ) : (
                            <span className="text-[11px] text-[#64748b] whitespace-nowrap">Generate replies →</span>
                          )}
                        </div>

                        <button
                          type="button"
                          onClick={handleGenerateWhatsAppDrafts}
                          disabled={isGeneratingWhatsAppDrafts}
                          className="inline-flex items-center gap-1 h-[26px] px-2.5 rounded-full text-[11px] font-medium text-[#1e40af] bg-white border border-[#bfdbfe] hover:bg-[#eff6ff] disabled:opacity-50 transition-colors cursor-pointer shrink-0 whitespace-nowrap"
                        >
                          <RotateCw
                            className={cn(
                              "w-3 h-3 text-[#2563eb]",
                              isGeneratingWhatsAppDrafts && "animate-spin"
                            )}
                          />
                          <span className="hidden sm:inline">{isGeneratingWhatsAppDrafts ? "Drafting..." : "Generate AI Drafts"}</span>
                          <span className="sm:hidden">{isGeneratingWhatsAppDrafts ? "Drafting..." : "Drafts"}</span>
                        </button>
                      </div>

                      {/* Chat Input Pill + Mic + Circular Send Button */}
                      <div className="flex items-end gap-2">
                        <div className="flex-1 min-w-0 flex items-end bg-white border-[1.5px] border-[#93c5fd] focus-within:border-[#2563eb] rounded-[22px] pl-3.5 pr-2 py-1.5 gap-1.5 min-h-[42px] shadow-[0_1px_4px_rgba(37,99,235,0.08)] transition-all">
                          <textarea
                            ref={whatsappTextareaRef}
                            rows={1}
                            value={whatsappInput}
                            onChange={(e) => setWhatsappInput(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                handleSendWhatsApp();
                              }
                            }}
                            placeholder={`Message ${activeContact.name} via WhatsApp...`}
                            className="flex-1 min-w-0 max-h-[96px] overflow-y-auto text-[14px] sm:text-[13px] leading-[1.35] bg-transparent outline-none text-[#111215] placeholder:text-[#8696a0] resize-none py-0.5"
                          />
                          <div className="flex items-center gap-1 shrink-0 pb-0.5">
                            <button
                              type="button"
                              onClick={handleToggleSpeechLang}
                              className={cn(
                                "text-[10px] font-bold px-1.5 py-0.5 rounded-full border transition-all cursor-pointer flex items-center gap-1 select-none shrink-0",
                                speechLang === "nl"
                                  ? "bg-amber-500/15 text-amber-700 border-amber-500/30 hover:bg-amber-500/25"
                                  : "bg-blue-500/15 text-blue-700 border-blue-500/30 hover:bg-blue-500/25"
                              )}
                              title={
                                speechLang === "nl"
                                  ? "Voice language: Nederlands (click to switch to English)"
                                  : "Voice language: English (click to switch to Nederlands)"
                              }
                            >
                              {speechLang === "nl" ? <FlagNL className="w-3 h-2" /> : <FlagUK className="w-3 h-2" />}
                              <span>{speechLang === "nl" ? "NL" : "EN"}</span>
                            </button>
                            <button
                              type="button"
                              onClick={() => handleToggleDictation("whatsapp", whatsappInput)}
                              className={cn(
                                "p-1.5 rounded-full cursor-pointer transition-all shrink-0 flex items-center justify-center",
                                activeVoiceTarget === "whatsapp"
                                  ? "bg-cyan-500 text-black shadow-[0_0_12px_rgba(0,229,255,0.7)] animate-pulse ring-2 ring-cyan-300"
                                  : "text-[#2563eb] hover:text-[#1d4ed8] hover:bg-[#eff6ff]"
                              )}
                              title={
                                activeVoiceTarget === "whatsapp"
                                  ? "Listening... click to stop"
                                  : `Voice dictation (${speechLang === "nl" ? "Dutch" : "English"})`
                              }
                              aria-label="Voice input for WhatsApp"
                            >
                              {activeVoiceTarget === "whatsapp" ? (
                                <MicOff className="w-4 h-4 stroke-[2.5]" />
                              ) : (
                                <Mic className="w-4 h-4" />
                              )}
                            </button>
                          </div>
                        </div>

                        {/* Send Button — 40px Circle Primary Blue */}
                        <button
                          type="button"
                          onClick={handleSendWhatsApp}
                          disabled={isSendingWhatsApp || !whatsappInput.trim()}
                          aria-label="Send WhatsApp message"
                          className="w-[40px] h-[40px] rounded-full bg-[#2563eb] hover:bg-[#1d4ed8] active:scale-95 text-white flex items-center justify-center shadow-[0_2px_8px_rgba(37,99,235,0.3)] transition-all cursor-pointer shrink-0 disabled:opacity-50"
                        >
                          <Send className="w-4 h-4 ml-0.5" />
                        </button>
                      </div>
                      {activeVoiceTarget === "whatsapp" && (
                        <div className="text-[11px] text-cyan-700 font-medium animate-pulse flex items-center gap-1.5 px-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-ping inline-block" />
                          <span>
                            {speechLang === "nl"
                              ? "Luisteren naar spraak (Nederlands)..."
                              : "Listening to speech (English)..."}
                          </span>
                        </div>
                      )}
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

      <ContactFormModal
        isOpen={contactForm.open}
        contact={contactForm.contact}
        onClose={() => setContactForm((f) => ({ ...f, open: false }))}
        onSaved={handleContactSaved}
      />
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
