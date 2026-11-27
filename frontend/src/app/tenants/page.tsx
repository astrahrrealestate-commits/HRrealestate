"use client";

import React, { useState, useMemo, useEffect, useRef, useCallback, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { ResizeHandle, usePersistedPaneSize } from "@/components/ui/ResizableSplit";
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
  ShieldCheck,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import { usePolling } from "@/hooks/usePolling";
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
  getMaintenanceTickets,
  type MaintenanceTicket,
} from "@/lib/api";
import { formatClock } from "@/lib/clock";
import { ContactFormModal } from "@/components/contacts/ContactFormModal";
import { TenantDocumentsPanel } from "@/components/contacts/TenantDocumentsPanel";
import type { SavedContact } from "@/lib/contactsWriteApi";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";
import { SHOWN_CATEGORIES } from "@/lib/categoryLabels";
import { useCachedState } from "@/hooks/useCachedState";
import { forgetView, readView, writeView } from "@/lib/viewCache";
import type { ContactCommunicationsData } from "@/lib/api";

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function getEmailPriority(email: ContactEmailItem): "emergency" | "high" | "normal" | "low" {
  if (email.priority) return email.priority;
  if (email.category === "maintenance") return "high";
  if (email.category === "finance" || email.category === "legal") return "normal";
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

function TenantsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantParam = searchParams.get("tenant") || searchParams.get("contact");
  const superAgent = useSuperAgent();
  const { t } = useLanguage();
  const { size: listWidth, applyDelta: resizeList, commitSize: commitList, resetSize: resetList } = usePersistedPaneSize("estateos_tenants_list_w", 240, 180, 420);

  const [contactForm, setContactForm] = useState<{ open: boolean; contact: ContactItem | null }>({
    open: false,
    contact: null,
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [leaseStatusFilter, setLeaseStatusFilter] = useState<"active" | "ending_soon" | "ended" | "all">("active");

  // Live Tenants loaded from database directory
  const [dbContacts, setDbContacts] = useCachedState<ContactItem[]>("tenants.list", []);
  const [isLoadingContacts, setIsLoadingContacts] = useState<boolean>(dbContacts.length === 0);

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
              agreementPeriod: t.leaseStart ? `${t.leaseStart} — ${t.leaseEnd || "open-ended"}` : "",
              leaseStart: t.leaseStart || null,
              leaseEnd: t.leaseEnd || null,
              monthlyRentEur: t.monthlyRentEur > 0 ? t.monthlyRentEur : null,
              depositEur: null,
              status: "active",
              rentStatus: t.rentStatus || "unknown",
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
  }, [setDbContacts]);

  // Profile Card Collapsed/Expanded state (#f0f5fb subtle blue; null = collapsed on <md mobile, expanded on >=md desktop)
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

  // Tickets raised by the active tenant: fetched (filtered by the API) while the Tickets tab is open. The result
  // remembers whose it is, so a slow answer for a previous tenant is never shown for the current one.
  const [ticketsFetch, setTicketsFetch] = useState<{
    forId: string;
    tickets: MaintenanceTicket[];
    live: boolean;
  } | null>(null);
  const activeContactId = activeContact?.id;
  useEffect(() => {
    if (activeTab !== "tickets" || !activeContactId) return;
    let isMounted = true;
    getMaintenanceTickets({ tenantId: activeContactId }).then(({ tickets, isLive }) => {
      if (isMounted) setTicketsFetch({ forId: activeContactId, tickets, live: isLive });
    });
    return () => {
      isMounted = false;
    };
  }, [activeContactId, activeTab]);
  const currentTickets = ticketsFetch && ticketsFetch.forId === activeContactId ? ticketsFetch : null;
  const tenantTickets = currentTickets?.tickets ?? [];
  const ticketsState: "loading" | "ready" | "unavailable" = !currentTickets
    ? "loading"
    : currentTickets.live
      ? "ready"
      : "unavailable";

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
  const openEmailIdRef = useRef<string | null>(null);
  openEmailIdRef.current = openEmailId;

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
      } else if (voiceTargetRef.current === "email" && openEmailIdRef.current) {
        const targetEmailId = openEmailIdRef.current;
        setEmailDraftCustomText((prev) => ({
          ...prev,
          [targetEmailId]: liveText,
        }));
      }
    },
  });

  useEffect(() => {
    if (!isListening) {
      voiceTargetRef.current = null;
      setVoiceTarget(null);
    }
  }, [isListening]);

  useEffect(() => {
    if (isListening) {
      stopListening();
    }
    voiceTargetRef.current = null;
    setVoiceTarget(null);
  }, [activeTab, activeContact?.id, openEmailId]);

  const handleToggleDictation = (target: "whatsapp" | "email", existingText: string) => {
    if (isListening && voiceTargetRef.current === target) {
      stopListening();
      voiceTargetRef.current = null;
      setVoiceTarget(null);
      return;
    }
    if (isListening) {
      stopListening();
    }
    voiceTargetRef.current = target;
    setVoiceTarget(target);
    startListening(existingText);
  };

  const handleToggleSpeechLang = () => {
    if (isListening) {
      stopListening();
      voiceTargetRef.current = null;
      setVoiceTarget(null);
    }
    setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"));
  };

  // Update Super Agent Context
  useEffect(() => {
    superAgent.setCurrentPageName("Tenants");
    if (activeContact) {
      superAgent.setSelectedContext(
        `Tenant Profile: ${activeContact.name} · Unit: ${activeContact.unitRole || "N/A"} · Phone: ${activeContact.phone} · Email: ${activeContact.email}`
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

  const activeContactIdRef = useRef<string | null>(null);
  const contactId = activeContact?.id ?? "";
  const contactEmail = activeContact?.email || undefined;
  const contactPhone = activeContact?.phone || undefined;
  useEffect(() => {
    activeContactIdRef.current = contactId || null;
  }, [contactId]);

  // A person opened before shows their messages at once; the poll below then brings anything new.
  useEffect(() => {
    const cached = readView<ContactCommunicationsData>(`comms.${contactId}`);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- swap to the newly selected person's cached copy
    setLiveEmails(cached?.emails || []);
    setLiveWhatsApp(cached?.whatsapp_messages || []);
    setWhatsAppDrafts(cached?.suggested_whatsapp_drafts || []);
  }, [contactId]);

  // Live background polling for tenant communications (pauses when tab is hidden)
  const fetchLiveComms = useCallback(async () => {
    if (!contactId) return;
    const requestedId = contactId;
    try {
      const comms = await getContactCommunications(requestedId, contactEmail, contactPhone);
      if (comms) writeView(`comms.${requestedId}`, comms);
      if (comms && activeContactIdRef.current === requestedId) {
        setLiveEmails(comms.emails || []);
        setLiveWhatsApp(comms.whatsapp_messages || []);
        setWhatsAppDrafts(comms.suggested_whatsapp_drafts || []);
      }
    } catch {
      // Silently preserve current state when backend is offline
    }
  }, [contactId, contactEmail, contactPhone]);

  usePolling(fetchLiveComms, 10000, {
    enabled: Boolean(contactId),
    restartKey: contactId,
  });

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
      forgetView(`comms.${activeContact.id}`);
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
          time: formatClock(new Date()),
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
    if (isListening) {
      stopListening();
    }
    setIsSendingWhatsApp(true);
    const text = whatsappInput.trim();

    try {
      forgetView(`comms.${activeContact.id}`);
      const res = await sendContactWhatsAppMessage(activeContact.id, text);
      if (res && res.success) {
        const newMsg: ContactWhatsAppMessage = {
          id: res.message_id,
          sender: "owner",
          text: text,
          time: formatClock(new Date()),
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

  const parseLeaseEndDate = (leaseEnd?: string | null): Date | null => {
    if (!leaseEnd) return null;
    const parts = leaseEnd.split(/[-/]/);
    if (parts.length === 3) {
      if (parts[0].length === 4) {
        return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      } else {
        return new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
      }
    }
    return null;
  };

  // Live counts for the lease status filter pills
  const leaseCounts = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const ninetyDays = new Date(today.getTime() + 90 * 24 * 60 * 60 * 1000);

    let living = 0;
    let endingSoon = 0;
    let ended = 0;

    for (const c of dbContacts) {
      const endDate = parseLeaseEndDate(c.leaseEnd);
      if (endDate !== null && endDate < today) {
        ended++;
      } else {
        living++;
        if (endDate !== null && endDate <= ninetyDays) {
          endingSoon++;
        }
      }
    }

    return {
      active: living,
      ending_soon: endingSoon,
      ended: ended,
      all: dbContacts.length,
    };
  }, [dbContacts]);

  // Filtered contacts list
  const filteredContacts = useMemo(() => {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const ninetyDays = new Date(today.getTime() + 90 * 24 * 60 * 60 * 1000);

    return dbContacts.filter((contact) => {
      // 1. Lease status filter
      if (leaseStatusFilter !== "all") {
        const endDate = parseLeaseEndDate(contact.leaseEnd);
        const isEnded = endDate !== null && endDate < today;
        const isEndingSoon = endDate !== null && endDate >= today && endDate <= ninetyDays;
        const isLiving = !endDate || endDate >= today;

        if (leaseStatusFilter === "active" && !isLiving) return false;
        if (leaseStatusFilter === "ending_soon" && !isEndingSoon) return false;
        if (leaseStatusFilter === "ended" && !isEnded) return false;
      }

      // 2. Search query filter
      if (searchQuery.trim()) {
        const q = searchQuery.trim().toLowerCase();
        const matchesName = contact.name.toLowerCase().includes(q);
        const matchesEmail = (contact.email ?? "").toLowerCase().includes(q);
        const matchesUnit = (contact.unitRole || "").toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesUnit) return false;
      }
      return true;
    });
  }, [dbContacts, searchQuery, leaseStatusFilter]);

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
    <div className="flex h-dvh bg-[#0A1B2F] overflow-hidden font-sans antialiased">

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar pageTitle="Tenants" hideSearch />

        <div className="flex-1 flex min-h-0 relative">
          <main className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#27272a] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex min-h-0 overflow-hidden min-w-0">
            {/* PANEL 1: TENANT LIST (Resizable on md+) */}
            <div
              style={{ ["--list-w" as string]: `${listWidth}px` }}
              className={cn(
                "w-full md:w-[var(--list-w)] shrink-0 border-r border-[#e8e9eb] bg-[#fafafa] flex flex-col overflow-hidden",
                tenantParam && "hidden md:flex"
              )}
            >
              {/* Header */}
              <div className="p-[14px_12px_10px] shrink-0 border-b border-[#e8e9eb] space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10.5px] font-bold text-[#64748b] tracking-[0.06em] uppercase">
                    {t("nav.tenants", "Tenants")}
                  </div>
                  <button
                    type="button"
                    onClick={() => setContactForm({ open: true, contact: null })}
                    title={t("tenants.add_tenant", "Add tenant")}
                    aria-label={t("tenants.add_tenant", "Add tenant")}
                    className="inline-flex items-center gap-1 h-[22px] px-2 rounded-[6px] bg-[#111215] text-white text-[10.5px] font-semibold hover:bg-[#27272a] transition-colors cursor-pointer"
                  >
                    <Plus className="w-3 h-3" />
                    <span>{t("common.add", "Add")}</span>
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

                {/* Lease Status Filter Pills */}
                <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pt-1">
                  {[
                    { id: "active", label: t("Currently living", "Currently living"), count: leaseCounts.active },
                    { id: "ending_soon", label: t("Ending soon", "Ending soon"), count: leaseCounts.ending_soon },
                    { id: "ended", label: t("Past tenants", "Past tenants"), count: leaseCounts.ended },
                    { id: "all", label: t("All", "All"), count: leaseCounts.all },
                  ].map((tab) => {
                    const isSelected = leaseStatusFilter === tab.id;
                    return (
                      <button
                        key={tab.id}
                        type="button"
                        onClick={() => setLeaseStatusFilter(tab.id as any)}
                        className={cn(
                          "inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-full font-medium whitespace-nowrap transition-all cursor-pointer select-none",
                          isSelected
                            ? "bg-[#0A1B2F] text-white font-semibold shadow-xs"
                            : "bg-white text-[#475569] border border-[#d5d9e0] hover:bg-[#f1f5f9] hover:text-[#0f172a]"
                        )}
                      >
                        <span>{tab.label}</span>
                        <span
                          className={cn(
                            "text-[10px] px-1.5 py-0.2 rounded-full tabular-nums shrink-0",
                            isSelected
                              ? tab.id === "ending_soon" && tab.count > 0
                                ? "bg-[var(--accent)] text-[#0A0A0A] font-bold"
                                : "bg-white/20 text-white font-semibold"
                              : tab.id === "ending_soon" && tab.count > 0
                                ? "bg-amber-100 text-amber-900 font-semibold"
                                : "bg-zinc-100 text-zinc-600"
                          )}
                        >
                          {tab.count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Contact items scroll */}
              <div className="flex-1 overflow-y-auto py-1.5 pb-[calc(4rem+env(safe-area-inset-bottom))] md:pb-1.5">
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
                        setMobileInfoPref({ contactId: contact.id, expanded: true });
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
                          <span className="shrink-0 flex items-center gap-1 ml-1.5">
                            {contact.leaseEnd && parseLeaseEndDate(contact.leaseEnd) && (
                              (() => {
                                const end = parseLeaseEndDate(contact.leaseEnd)!;
                                const now = new Date();
                                now.setHours(0, 0, 0, 0);
                                const ninety = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000);
                                if (end < now) {
                                  return (
                                    <span className="text-[10px] font-medium text-rose-700 bg-rose-50 border border-rose-200 px-1.5 py-0.2 rounded">
                                      Vacated
                                    </span>
                                  );
                                } else if (end <= ninety) {
                                  return (
                                    <span className="text-[10px] font-medium text-amber-800 bg-amber-50 border border-amber-200 px-1.5 py-0.2 rounded">
                                      Ends soon
                                    </span>
                                  );
                                }
                                return null;
                              })()
                            )}
                            {contact.rentStatus === "overdue" && (
                              <span
                                className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-800 bg-amber-50 border border-amber-200/80 px-1.5 py-0.2 rounded"
                                title={t("Billed in BRIXX; bank settlement in Exact Online", "Billed in BRIXX; bank settlement in Exact Online")}
                              >
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                                {t("Unreconciled", "Unreconciled")}
                              </span>
                            )}
                          </span>
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

            <ResizeHandle
              orientation="horizontal"
              ariaLabel="Resize tenants list"
              className="hidden md:block"
              onDragDelta={resizeList}
              onDragEnd={commitList}
              onDoubleClick={resetList}
            />

            {/* PANEL 2: TENANT DETAIL */}
            <div
              className={cn(
                "flex-1 flex flex-col min-h-0 overflow-hidden relative pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0",
                !tenantParam && "hidden md:flex"
              )}
            >
              {/* Compact sticky bar on mobile: Back + Name + Info dropdown */}
              <div className="md:hidden flex items-center justify-between gap-2 px-3 py-2 border-b border-[#e8e9eb] bg-[#fafafa] shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    type="button"
                    onClick={() => router.push("/tenants")}
                    className="inline-flex items-center gap-1 text-xs text-[#475569] font-medium shrink-0 py-0.5 pr-1"
                    aria-label="Back to All Tenants"
                  >
                    <ArrowLeft className="w-4 h-4" />
                    {!activeContact && <span>All Tenants</span>}
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
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        Tenant
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
                    <p>No tenant selected.</p>
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
                            <span className="w-1.5 h-1.5 rounded-full bg-[#2563eb]" />
                            Tenant
                          </span>
                          {activeContact.rentStatus === "overdue" ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[10.5px] font-semibold rounded-full capitalize bg-white text-[#1e293b] border border-[#e2e8f0]">
                              <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                              {t("Rent overdue", "Rent overdue")}
                            </span>
                          ) : activeContact.rentStatus === "up_to_date" ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 text-[10.5px] font-semibold rounded-full capitalize bg-white text-[#1e293b] border border-[#e2e8f0]">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                              {t("Rent up to date", "Rent up to date")}
                            </span>
                          ) : null}
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
                              {activeContact.agreementPeriod || "—"}
                            </span>
                          </div>
                        </div>

                        {/* Secondary contacts if present */}
                        {(activeContact.secondaryPhones?.length || activeContact.secondaryEmails?.length) ? (
                          <div className="flex items-center gap-2 flex-wrap text-[11px] text-[#64748b] mt-0.5">
                            <span className="font-semibold text-[#475569]">Secondary:</span>
                            {activeContact.secondaryPhones?.map((p) => (
                              <a key={p} href={`tel:${p}`} className="inline-flex items-center gap-0.5 hover:text-[#111215]">
                                <Phone className="w-2.5 h-2.5 text-[#64748b]" />
                                <span>{p}</span>
                              </a>
                            ))}
                            {activeContact.secondaryEmails?.map((e) => (
                              <a key={e} href={`mailto:${e}`} className="inline-flex items-center gap-0.5 hover:text-[#111215]">
                                <Mail className="w-2.5 h-2.5 text-[#64748b]" />
                                <span>{e}</span>
                              </a>
                            ))}
                          </div>
                        ) : null}
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
                          {activeContact.propertyAddress || activeContact.address || "—"}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* LEASE & TENANCY SPECS (Desktop always shown; on mobile shown first or via Info dropdown) */}
                  <div
                    className={cn(
                      "grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 sm:gap-3 p-3.5 sm:p-4 bg-white border-b border-[#e5e7eb] shrink-0",
                      isMobileInfoExpanded ? "grid" : "hidden md:grid"
                    )}
                  >
                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Monthly Rent")}
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        {eur(activeContact.monthlyRentEur)}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Security Deposit")}
                      </div>
                      <div className="text-[14px] font-bold text-[#0f172a] mt-1 font-mono">
                        {eur(activeContact.depositEur)}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Lease Commencement")}
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        {activeContact.leaseStart || "—"}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Lease Expiry")}
                      </div>
                      <div className="text-[13px] font-semibold text-[#0f172a] mt-1 font-mono">
                        {activeContact.leaseEnd || (activeContact.leaseStart ? t("Open-ended") : "—")}
                      </div>
                    </div>

                    <div className="p-2.5 rounded-[8px] bg-[#f8fafc] border border-[#e2e8f0]">
                      <div className="text-[10px] font-bold text-[#64748b] uppercase tracking-wider">
                        {t("Payment Status")}
                      </div>
                      <div
                        className={cn(
                          "text-[12px] font-bold mt-1",
                          activeContact.rentStatus === "overdue"
                            ? "text-amber-800"
                            : activeContact.rentStatus === "up_to_date"
                              ? "text-emerald-700"
                              : "text-[#64748b]"
                        )}
                        title={activeContact.rentStatus === "overdue" ? t("Billed in BRIXX; bank settlement handled in Exact Online", "Billed in BRIXX; bank settlement handled in Exact Online") : undefined}
                      >
                        {activeContact.rentStatus === "overdue"
                          ? t("Unreconciled (Exact Online)", "Unreconciled (Exact Online)")
                          : activeContact.rentStatus === "up_to_date"
                            ? t("Rent up to date")
                            : t("No rent records yet")}
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
                      onClick={() => handleSelectTab("whatsapp", activeContact.id)}
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
                      onClick={() => handleSelectTab("brixx", activeContact.id)}
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
                      onClick={() => handleSelectTab("tickets", activeContact.id)}
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

                  {/* TAB VIEW 1: Mail Inbox (matching Contacts Mail Inbox UI) */}
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
                                {["all", ...SHOWN_CATEGORIES].map((cat) => (
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
                              <span className="capitalize">
                                {mailPriorityFilter === "all" ? t("Priority", "Prioriteit") : `${t("Priority", "Prioriteit")}: ${t(mailPriorityFilter)}`}
                              </span>
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

                      {/* Email Thread Opened View (Like Gmail / Contacts: full thread viewer inside) */}
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
                                    handleToggleDictation("email", currentEmailBody);
                                  }}
                                  className={cn(
                                    "px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 shrink-0 border select-none",
                                    isListening && voiceTarget === "email"
                                      ? "bg-cyan-500 text-black border-cyan-400 shadow-[0_0_12px_rgba(0,229,255,0.6)] animate-pulse font-semibold ring-2 ring-cyan-300"
                                      : "bg-white hover:bg-[#f1f5f9] text-[#334155] hover:text-[#111215] border-[#cbd5e1]"
                                  )}
                                  title={
                                    isListening && voiceTarget === "email"
                                      ? "Listening... click to stop"
                                      : `Voice dictation (${speechLang === "nl" ? "Dutch" : "English"})`
                                  }
                                  aria-label="Voice dictation for email reply"
                                >
                                  {isListening && voiceTarget === "email" ? (
                                    <MicOff className="w-3.5 h-3.5 text-black stroke-[2.5]" />
                                  ) : (
                                    <Mic className="w-3.5 h-3.5 text-[#1a73e8] stroke-[2]" />
                                  )}
                                  <span>{isListening && voiceTarget === "email" ? "Listening..." : "Dictate"}</span>
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

                                {isListening && voiceTarget === "email" ? (
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
                        /* Flat Mail List (matching Contacts UI) */
                        <div className="flex-1 overflow-y-auto divide-y divide-[#f3f4f6]">
                          {filteredEmails.map((email) => (
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
                          ))}

                          {filteredEmails.length === 0 && (
                            <div className="text-center py-16 text-[#94a3b8] text-xs">
                              No email messages on file for this tenant.
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* TAB VIEW 2: WhatsApp Chat */}
                  {activeTab === "whatsapp" && (
                    <div className="flex-1 flex flex-col min-h-0 md:min-h-[420px] bg-[#e5ddd5] overflow-hidden">
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
                            No previous WhatsApp messages recorded in database for this tenant.
                          </div>
                        )}
                      </div>

                      {/* WhatsApp Chat Bar — Subtle AI Blue theme */}
                      <div className="p-2.5 sm:p-3 bg-[#f0f7ff] border-t border-[#bfdbfe] flex flex-col gap-2 shrink-0">
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
                                  isListening && voiceTarget === "whatsapp"
                                    ? "bg-cyan-500 text-black shadow-[0_0_12px_rgba(0,229,255,0.7)] animate-pulse ring-2 ring-cyan-300"
                                    : "text-[#2563eb] hover:text-[#1d4ed8] hover:bg-[#eff6ff]"
                                )}
                                title={
                                  isListening && voiceTarget === "whatsapp"
                                    ? "Listening... click to stop"
                                    : `Voice dictation (${speechLang === "nl" ? "Dutch" : "English"})`
                                }
                                aria-label="Voice input for WhatsApp"
                              >
                                {isListening && voiceTarget === "whatsapp" ? (
                                  <MicOff className="w-4 h-4 stroke-[2.5]" />
                                ) : (
                                  <Mic className="w-4 h-4" />
                                )}
                              </button>
                            </div>
                          </div>

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
                        {isListening && voiceTarget === "whatsapp" && (
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
                    <div className="flex-1 flex flex-col p-3.5 sm:p-6 space-y-4 bg-white">
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
                          <div className="col-span-2 text-center py-8 text-[#94a3b8] text-xs border border-dashed border-[#e2e8f0] rounded-xl">
                            No lease agreements currently on file.
                          </div>
                        )}
                      </div>

                      <TenantDocumentsPanel tenantId={activeContact.id} name={activeContact.name} embedded />
                    </div>
                  )}

                  {/* TAB VIEW 4: Tickets */}
                  {activeTab === "tickets" && (
                    <div className="flex-1 flex flex-col p-3.5 sm:p-6 space-y-4 bg-white">
                      {tenantTickets.length > 0 ? (
                        <ul className="space-y-2">
                          {tenantTickets.map((tk) => (
                            <li key={tk.id}>
                              <button
                                type="button"
                                onClick={() => router.push(`/maintenance?ticket=${encodeURIComponent(tk.id)}`)}
                                className="w-full text-left p-3 rounded-[8px] border border-[#e2e8f0] hover:bg-[#f8fafc] cursor-pointer"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-sm font-semibold text-[#111215] truncate">{tk.issueTitle}</span>
                                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[#475569] shrink-0">
                                    {tk.status.replace(/_/g, " ")}
                                  </span>
                                </div>
                                <div className="text-xs text-[#64748b] mt-1">
                                  {tk.ticketNumber}
                                  {tk.unitLabel ? ` · ${tk.unitLabel}` : ""}
                                  {tk.reportedAt ? ` · ${tk.reportedAt}` : ""}
                                  {tk.contractorName ? ` · ${tk.contractorName}` : ""}
                                </div>
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <div className="flex-1 flex flex-col items-center justify-center p-12 text-center bg-white border border-dashed border-[#e2e8f0] rounded-[8px]">
                          <div className="w-12 h-12 rounded-full bg-[#f1f5f9] flex items-center justify-center text-[#64748b] mb-3">
                            <Wrench className="w-5 h-5 stroke-[1.5]" />
                          </div>
                          <h3 className="text-sm font-semibold text-[#111215]">
                            {ticketsState === "loading"
                              ? "Loading tickets..."
                              : ticketsState === "unavailable"
                                ? "Tickets unavailable"
                                : "No tickets"}
                          </h3>
                          {ticketsState !== "loading" && (
                            <p className="text-xs text-[#64748b] max-w-sm mt-1">
                              {ticketsState === "unavailable"
                                ? "Could not reach the server. Try again in a moment."
                                : `There are no tickets logged for ${activeContact.name}.`}
                            </p>
                          )}
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

/** A euro amount the API knows, else "—" (never a made-up figure). */
function eur(amount: number | null | undefined): string {
  return amount == null
    ? "—"
    : `€ ${amount.toLocaleString("nl-NL", { minimumFractionDigits: 0, maximumFractionDigits: 2 })},-`;
}

export default function TenantsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-zinc-400">Loading tenants...</div>}>
      <TenantsContent />
    </Suspense>
  );
}
