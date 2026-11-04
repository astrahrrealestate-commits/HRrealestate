"use client";

import React, { useState, useMemo, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import {
  Search,
  Star,
  Paperclip,
  Clock,
  Mail,
  MessageSquare,
  FileText,
  Wrench,
  Pencil,
  MoreVertical,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  History,
  Send,
  Building,
  CheckCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  MOCK_CONTACTS,
  ContactItem,
  ContactEmailItem,
} from "@/data/contactsMockData";

function ContactsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const contactParam = searchParams.get("contact");

  const [activeTab, setActiveTab] = useState<"tenants" | "contractors">("tenants");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedContactId, setSelectedContactId] = useState<string>(
    contactParam || MOCK_CONTACTS[0].id
  );

  // Detail pane tabs: "mail" | "whatsapp" | "brixx" | "maintenance"
  const [activeSection, setActiveSection] = useState<
    "mail" | "whatsapp" | "brixx" | "maintenance"
  >("mail");

  // Mail filter chips: "all" | "recent" | "unread" | "attachments" | "historical"
  const [mailFilter, setMailFilter] = useState<
    "all" | "recent" | "unread" | "attachments" | "historical"
  >("all");
  const [mailSearch, setMailSearch] = useState("");

  // Expanded email item for reading
  const [expandedEmailId, setExpandedEmailId] = useState<string | null>("m-1");
  const [starredEmails, setStarredEmails] = useState<Record<string, boolean>>({});

  // Sync state if URL changes
  useEffect(() => {
    if (contactParam && MOCK_CONTACTS.some((c) => c.id === contactParam)) {
      setSelectedContactId(contactParam);
    }
  }, [contactParam]);

  // Derived active contact
  const activeContact = useMemo(() => {
    return (
      MOCK_CONTACTS.find((c) => c.id === selectedContactId) ||
      MOCK_CONTACTS[0]
    );
  }, [selectedContactId]);

  // Filtered contacts in the left list
  const filteredContacts = useMemo(() => {
    return MOCK_CONTACTS.filter((contact) => {
      if (activeTab === "tenants" && contact.category !== "tenant") return false;
      if (activeTab === "contractors" && contact.category !== "contractor") return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = contact.name.toLowerCase().includes(q);
        const matchesEmail = contact.email.toLowerCase().includes(q);
        const matchesUnit = (contact.unitRole || "").toLowerCase().includes(q);
        if (!matchesName && !matchesEmail && !matchesUnit) return false;
      }
      return true;
    });
  }, [activeTab, searchQuery]);

  // Filtered emails for the active contact
  const filteredEmails = useMemo(() => {
    if (!activeContact?.emails) return [];
    return activeContact.emails.filter((email) => {
      // Filter chips
      if (mailFilter === "recent" && email.date !== "Today" && email.date !== "Yesterday") {
        return false;
      }
      if (mailFilter === "unread" && !email.isUnread) {
        return false;
      }
      if (mailFilter === "attachments" && !email.hasAttachments) {
        return false;
      }
      if (mailFilter === "historical" && !email.isHistorical) {
        return false;
      }

      // Search within emails
      if (mailSearch.trim()) {
        const q = mailSearch.toLowerCase();
        const matchesSubject = email.subject.toLowerCase().includes(q);
        const matchesSnippet = email.snippet.toLowerCase().includes(q);
        if (!matchesSubject && !matchesSnippet) return false;
      }

      return true;
    });
  }, [activeContact, mailFilter, mailSearch]);

  const toggleStar = (e: React.MouseEvent, emailId: string) => {
    e.stopPropagation();
    setStarredEmails((prev) => ({
      ...prev,
      [emailId]: !prev[emailId],
    }));
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--background)] font-sans antialiased text-[var(--ink)]">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Area */}
      <div className="flex flex-col flex-1 min-w-0 h-full overflow-hidden">
        {/* Top Command Bar */}
        <TopCommandBar pageTitle="Contacts" hideSearch={true} />

        {/* Content Body: Two columns layout */}
        <div className="flex flex-1 min-h-0 overflow-hidden bg-[var(--pane)] border-t border-[var(--line)]">
          {/* COLUMN 1: Contact List (Width 310px) */}
          <div className="w-full md:w-[310px] xl:w-[330px] border-r border-[var(--line)] flex flex-col bg-[var(--pane)] shrink-0">
            {/* Header & Search */}
            <div className="p-4 border-b border-[var(--line)] space-y-3">
              <h1 className="text-[17px] font-bold text-[var(--ink)] tracking-tight">
                Contacts
              </h1>

              {/* Search contacts input */}
              <div className="relative">
                <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search contacts..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 rounded-lg text-xs bg-zinc-100 dark:bg-zinc-800/70 border border-zinc-200 dark:border-zinc-700/60 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 transition-all"
                />
              </div>

              {/* Tenants / Contractors toggle buttons */}
              <div className="flex items-center gap-1.5 pt-1">
                <button
                  onClick={() => setActiveTab("tenants")}
                  className={cn(
                    "px-4 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer",
                    activeTab === "tenants"
                      ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 shadow-2xs"
                      : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  )}
                >
                  Tenants
                </button>
                <button
                  onClick={() => setActiveTab("contractors")}
                  className={cn(
                    "px-4 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer",
                    activeTab === "contractors"
                      ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 shadow-2xs"
                      : "text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  )}
                >
                  Contractors
                </button>
              </div>
            </div>

            {/* Contact Rows List */}
            <div className="flex-1 overflow-y-auto divide-y divide-zinc-100 dark:divide-zinc-800/60 p-2 space-y-1">
              {filteredContacts.map((contact) => {
                const isSelected = contact.id === activeContact?.id;

                return (
                  <button
                    key={contact.id}
                    onClick={() => {
                      setSelectedContactId(contact.id);
                      router.push(`/contacts?contact=${contact.id}`);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-2.5 rounded-xl transition-all flex items-center gap-3 cursor-pointer",
                      isSelected
                        ? "bg-zinc-100 dark:bg-zinc-800/90 text-zinc-900 dark:text-zinc-100"
                        : "hover:bg-zinc-50 dark:hover:bg-zinc-800/40 text-zinc-700 dark:text-zinc-300"
                    )}
                  >
                    {/* User Avatar Photo */}
                    <div className="w-9 h-9 rounded-full overflow-hidden bg-zinc-200 dark:bg-zinc-700 shrink-0 border border-zinc-200/80 dark:border-zinc-700">
                      {contact.avatarUrl ? (
                        <img
                          src={contact.avatarUrl}
                          alt={contact.name}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-xs font-bold text-zinc-600 dark:text-zinc-300">
                          {contact.name.slice(0, 2).toUpperCase()}
                        </div>
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-semibold truncate leading-snug">
                        {contact.name}
                      </div>
                      <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate">
                        {contact.unitRole || contact.tradeOrRole}
                      </div>
                    </div>
                  </button>
                );
              })}

              {filteredContacts.length === 0 && (
                <div className="text-center py-16 text-zinc-400 text-xs">
                  No contacts found.
                </div>
              )}
            </div>
          </div>

          {/* COLUMN 2: Main Profile & Tabs Pane */}
          {activeContact && (
            <div className="flex-1 flex flex-col min-w-0 h-full overflow-y-auto bg-white dark:bg-[#18181b]">
              {/* Header Breadcrumb & Actions */}
              <div className="px-8 pt-5 pb-3 flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800/80">
                <div className="text-xs text-zinc-400">
                  Contacts / <span className="text-zinc-700 dark:text-zinc-200 font-medium">{activeContact.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <button className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-600 dark:text-zinc-300 border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer">
                    <Pencil className="w-3.5 h-3.5" />
                    Edit
                  </button>
                  <button className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer">
                    <MoreVertical className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Profile Card Header */}
              <div className="px-8 py-6 border-b border-zinc-100 dark:border-zinc-800/80">
                <div className="flex items-start gap-5">
                  {/* Avatar Photo */}
                  <div className="w-20 h-20 rounded-full overflow-hidden bg-zinc-200 dark:bg-zinc-700 shrink-0 border-2 border-zinc-200 dark:border-zinc-700 shadow-xs">
                    {activeContact.avatarUrl ? (
                      <img
                        src={activeContact.avatarUrl}
                        alt={activeContact.name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-xl font-bold text-zinc-600">
                        {activeContact.name.slice(0, 2).toUpperCase()}
                      </div>
                    )}
                  </div>

                  {/* Metadata Grid */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h2 className="text-[20px] font-bold text-zinc-900 dark:text-zinc-100 leading-tight">
                        {activeContact.name}
                      </h2>
                      <span className="px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200/60 dark:border-emerald-800/50 capitalize">
                        {activeContact.category}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-3 gap-y-3 gap-x-6 mt-4 text-xs">
                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          PHONE
                        </span>
                        <span className="font-mono text-zinc-800 dark:text-zinc-200 mt-0.5 block">
                          {activeContact.phone}
                        </span>
                      </div>

                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          EMAIL
                        </span>
                        <span className="text-zinc-800 dark:text-zinc-200 mt-0.5 block truncate">
                          {activeContact.email}
                        </span>
                      </div>

                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          UNIT / ROLE
                        </span>
                        <span className="text-zinc-800 dark:text-zinc-200 mt-0.5 block font-medium">
                          {activeContact.unitRole || activeContact.tradeOrRole}
                        </span>
                      </div>

                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          PROPERTY ADDRESS
                        </span>
                        <span className="text-zinc-800 dark:text-zinc-200 mt-0.5 block">
                          {activeContact.propertyAddress || activeContact.address || "14-22 St. Mark's Square, London"}
                        </span>
                      </div>

                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          RESIDENTIAL ADDRESS
                        </span>
                        <span className="text-zinc-800 dark:text-zinc-200 mt-0.5 block">
                          {activeContact.residentialAddress || activeContact.address || "14-22 St. Mark's Square, Unit 12"}
                        </span>
                      </div>

                      <div>
                        <span className="text-zinc-400 text-[10px] uppercase font-bold tracking-wider block">
                          AGREEMENT PERIOD
                        </span>
                        <span className="font-mono text-zinc-800 dark:text-zinc-200 mt-0.5 block">
                          {activeContact.agreementPeriod || "01 Jan 2024 — 31 Dec 2024"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Navigation Tabs Bar */}
              <div className="px-8 border-b border-zinc-100 dark:border-zinc-800/80 flex items-center gap-6">
                <button
                  onClick={() => setActiveSection("mail")}
                  className={cn(
                    "py-3.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all cursor-pointer",
                    activeSection === "mail"
                      ? "border-black dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
                      : "border-transparent text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300"
                  )}
                >
                  <Mail className="w-3.5 h-3.5" />
                  Mail Inbox
                </button>

                <button
                  onClick={() => setActiveSection("whatsapp")}
                  className={cn(
                    "py-3.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all cursor-pointer",
                    activeSection === "whatsapp"
                      ? "border-black dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
                      : "border-transparent text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300"
                  )}
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  WhatsApp
                </button>

                <button
                  onClick={() => setActiveSection("brixx")}
                  className={cn(
                    "py-3.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all cursor-pointer",
                    activeSection === "brixx"
                      ? "border-black dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
                      : "border-transparent text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300"
                  )}
                >
                  <FileText className="w-3.5 h-3.5" />
                  Brixx Data (Lease Agreements)
                </button>

                <button
                  onClick={() => setActiveSection("maintenance")}
                  className={cn(
                    "py-3.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all cursor-pointer",
                    activeSection === "maintenance"
                      ? "border-black dark:border-zinc-100 text-zinc-900 dark:text-zinc-100"
                      : "border-transparent text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-300"
                  )}
                >
                  <Wrench className="w-3.5 h-3.5" />
                  Maintenance
                </button>
              </div>

              {/* TAB 1: Mail Inbox */}
              {activeSection === "mail" && (
                <div className="flex-1 flex flex-col p-8 space-y-4">
                  {/* Filter chips bar & search */}
                  <div className="flex items-center justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <button
                        onClick={() => setMailFilter("all")}
                        className={cn(
                          "px-3 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer",
                          mailFilter === "all"
                            ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900"
                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200"
                        )}
                      >
                        All
                      </button>

                      <button
                        onClick={() => setMailFilter("recent")}
                        className={cn(
                          "px-3 py-1 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer",
                          mailFilter === "recent"
                            ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900"
                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200"
                        )}
                      >
                        <Clock className="w-3 h-3" />
                        Recent
                      </button>

                      <button
                        onClick={() => setMailFilter("unread")}
                        className={cn(
                          "px-3 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer",
                          mailFilter === "unread"
                            ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900"
                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200"
                        )}
                      >
                        Unread
                      </button>

                      <button
                        onClick={() => setMailFilter("attachments")}
                        className={cn(
                          "px-3 py-1 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer",
                          mailFilter === "attachments"
                            ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900"
                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200"
                        )}
                      >
                        <Paperclip className="w-3 h-3" />
                        Attachments
                      </button>

                      <button
                        onClick={() => setMailFilter("historical")}
                        className={cn(
                          "px-3 py-1 rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer",
                          mailFilter === "historical"
                            ? "bg-black dark:bg-zinc-100 text-white dark:text-zinc-900"
                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200"
                        )}
                      >
                        <History className="w-3 h-3" />
                        Historical Mail
                      </button>
                    </div>

                    {/* Search mail input */}
                    <div className="relative">
                      <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                      <input
                        type="text"
                        placeholder="Search mail..."
                        value={mailSearch}
                        onChange={(e) => setMailSearch(e.target.value)}
                        className="pl-8 pr-3 py-1 rounded-md text-xs bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700/60 text-zinc-700 dark:text-zinc-200 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 w-48"
                      />
                    </div>
                  </div>

                  {/* Gmail Style Email Rows */}
                  <div className="border border-zinc-200 dark:border-zinc-800 rounded-xl overflow-hidden divide-y divide-zinc-100 dark:divide-zinc-800/80 bg-white dark:bg-[#18181b] shadow-2xs">
                    {filteredEmails.map((email) => {
                      const isExpanded = expandedEmailId === email.id;
                      const isStarred = starredEmails[email.id] || email.starred;

                      return (
                        <div key={email.id} className="transition-colors">
                          <div
                            onClick={() =>
                              setExpandedEmailId(isExpanded ? null : email.id)
                            }
                            className={cn(
                              "px-4 py-3 flex items-center gap-3.5 text-xs cursor-pointer select-none transition-colors",
                              email.isUnread
                                ? "bg-zinc-50/70 dark:bg-zinc-800/40 font-semibold"
                                : "hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20"
                            )}
                          >
                            {/* Star Icon */}
                            <button
                              onClick={(e) => toggleStar(e, email.id)}
                              className="text-zinc-300 hover:text-amber-400 transition-colors p-0.5"
                            >
                              <Star
                                className={cn(
                                  "w-4 h-4",
                                  isStarred && "fill-amber-400 text-amber-400"
                                )}
                              />
                            </button>

                            {/* Sender Name */}
                            <span className="w-32 truncate text-zinc-900 dark:text-zinc-100 shrink-0 font-medium">
                              {email.sender}
                            </span>

                            {/* Subject & Snippet */}
                            <div className="flex-1 min-w-0 flex items-center gap-2 truncate">
                              <span className="text-zinc-800 dark:text-zinc-200 truncate">
                                {email.subject}
                              </span>
                              <span className="text-zinc-400 font-normal truncate hidden sm:inline">
                                — {email.snippet}
                              </span>
                            </div>

                            {/* Badges / Attachment clip */}
                            {email.hasAttachments && (
                              <Paperclip className="w-3.5 h-3.5 text-zinc-400 shrink-0" />
                            )}
                            {email.isHistorical && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 border border-zinc-200 dark:border-zinc-700 shrink-0">
                                Historical
                              </span>
                            )}

                            {/* Timestamp */}
                            <span className="text-[11.5px] text-zinc-400 shrink-0 font-mono">
                              {email.time}
                            </span>
                          </div>

                          {/* Expanded Email Body Preview */}
                          {isExpanded && (
                            <div className="px-6 py-4 bg-zinc-50/50 dark:bg-zinc-900/40 border-t border-zinc-100 dark:border-zinc-800/80 space-y-3">
                              <div className="flex items-start justify-between text-xs">
                                <div>
                                  <div className="font-semibold text-zinc-900 dark:text-zinc-100 text-sm">
                                    {email.subject}
                                  </div>
                                  <div className="text-zinc-400 text-[11px] mt-0.5">
                                    From: <span className="font-mono text-zinc-600 dark:text-zinc-300">{email.senderEmail}</span> · Date: {email.date}
                                  </div>
                                </div>
                                <span className="text-[11px] text-zinc-400 font-mono">
                                  {email.time}
                                </span>
                              </div>

                              <div className="text-xs text-zinc-700 dark:text-zinc-300 leading-relaxed whitespace-pre-line pt-2">
                                {email.body}
                              </div>

                              {email.hasAttachments && (
                                <div className="pt-2 flex items-center gap-2">
                                  <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-xs text-zinc-700 dark:text-zinc-200 shadow-2xs">
                                    <Paperclip className="w-3.5 h-3.5 text-zinc-400" />
                                    <span>lease_agreement_countersigned_2024.pdf</span>
                                    <span className="text-zinc-400 text-[10px]">(2.4 MB)</span>
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {filteredEmails.length === 0 && (
                      <div className="text-center py-16 text-zinc-400 text-xs">
                        No emails match this filter.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: WhatsApp Chat */}
              {activeSection === "whatsapp" && (
                <div className="flex-1 flex flex-col p-8 space-y-4">
                  <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800/80 pb-3">
                    <div>
                      <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        WhatsApp Conversation · {activeContact.name}
                      </h3>
                      <p className="text-xs text-zinc-400 mt-0.5">
                        Connected to Desk (+31 6 3648 40587) · Synced live
                      </p>
                    </div>
                  </div>

                  {/* WhatsApp Messages Feed */}
                  <div className="flex-1 min-h-[320px] bg-zinc-50 dark:bg-zinc-900/30 border border-zinc-200 dark:border-zinc-800 rounded-xl p-6 overflow-y-auto space-y-4">
                    {activeContact.whatsappMessages && activeContact.whatsappMessages.length > 0 ? (
                      activeContact.whatsappMessages.map((msg) => {
                        const isTenant = msg.sender === "tenant";

                        return (
                          <div
                            key={msg.id}
                            className={cn(
                              "flex flex-col max-w-[70%]",
                              isTenant ? "mr-auto items-start" : "ml-auto items-end"
                            )}
                          >
                            <div
                              className={cn(
                                "px-4 py-2.5 rounded-2xl text-xs leading-relaxed shadow-2xs",
                                isTenant
                                  ? "bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-100 border border-zinc-200/80 dark:border-zinc-700/60 rounded-tl-xs"
                                  : "bg-emerald-600 text-white rounded-tr-xs"
                              )}
                            >
                              {msg.text}
                            </div>
                            <div className="flex items-center gap-1 text-[10px] text-zinc-400 font-mono mt-1 px-1">
                              <span>{msg.time}</span>
                              {!isTenant && <CheckCheck className="w-3 h-3 text-emerald-600" />}
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="text-center py-20 text-zinc-400 text-xs">
                        No previous WhatsApp conversations recorded for this contact.
                      </div>
                    )}
                  </div>

                  {/* Quick message composer */}
                  <div className="flex items-center gap-2 pt-2">
                    <input
                      type="text"
                      placeholder={`Message ${activeContact.name} via WhatsApp...`}
                      className="flex-1 px-4 py-2 rounded-lg text-xs bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400"
                    />
                    <button className="px-4 py-2 rounded-lg bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 font-medium text-xs flex items-center gap-1.5 hover:bg-zinc-800 transition-colors cursor-pointer shadow-2xs">
                      <Send className="w-3.5 h-3.5" />
                      Send
                    </button>
                  </div>
                </div>
              )}

              {/* TAB 3: Brixx Data (All Lease Agreements) */}
              {activeSection === "brixx" && (
                <div className="flex-1 flex flex-col p-8 space-y-6">
                  <div>
                    <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                      Brixx Financial Data & Lease Agreements
                    </h3>
                    <p className="text-xs text-zinc-400 mt-0.5">
                      All tenancy contracts, indexation schedules, and deposit guarantees recorded for {activeContact.name}
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {activeContact.leases && activeContact.leases.length > 0 ? (
                      activeContact.leases.map((lease) => (
                        <div
                          key={lease.id}
                          className="p-5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-[#18181b] shadow-2xs space-y-3"
                        >
                          <div className="flex items-start justify-between">
                            <div>
                              <h4 className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                                {lease.title}
                              </h4>
                              <p className="text-[11px] font-mono text-zinc-400 mt-0.5">
                                {lease.period}
                              </p>
                            </div>
                            <span
                              className={cn(
                                "px-2 py-0.5 rounded text-[10px] font-semibold border capitalize",
                                lease.status === "active"
                                  ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200/60"
                                  : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200/60"
                              )}
                            >
                              {lease.status.replace("_", " ")}
                            </span>
                          </div>

                          <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
                            <div>
                              <span className="text-[10px] text-zinc-400 uppercase font-bold block">
                                MONTHLY RENT
                              </span>
                              <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                                {lease.monthlyRent}
                              </span>
                            </div>
                            <div>
                              <span className="text-[10px] text-zinc-400 uppercase font-bold block">
                                DEPOSIT HELD
                              </span>
                              <span className="font-mono text-zinc-700 dark:text-zinc-300">
                                {lease.deposit}
                              </span>
                            </div>
                          </div>

                          <div className="pt-2 flex items-center justify-between text-xs text-zinc-400">
                            <span>Signed: {lease.signedDate}</span>
                            <button className="text-xs font-semibold text-zinc-900 dark:text-zinc-100 hover:underline flex items-center gap-1 cursor-pointer">
                              <FileText className="w-3.5 h-3.5" />
                              View Contract
                            </button>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="col-span-2 text-center py-16 text-zinc-400 text-xs border border-dashed border-zinc-200 dark:border-zinc-800 rounded-xl">
                        No lease contracts uploaded for this contact.
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 4: Maintenance (Kept Empty per user request) */}
              {activeSection === "maintenance" && (
                <div className="flex-1 flex flex-col items-center justify-center p-12 text-center">
                  <div className="w-12 h-12 rounded-2xl bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-400 mb-3">
                    <Wrench className="w-5 h-5 stroke-[1.5]" />
                  </div>
                  <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                    No active maintenance tickets
                  </h3>
                  <p className="text-xs text-zinc-400 max-w-sm mt-1">
                    There are currently no open work orders, repairs, or contractor dispatches logged for {activeContact.name}.
                  </p>
                </div>
              )}
            </div>
          )}
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
