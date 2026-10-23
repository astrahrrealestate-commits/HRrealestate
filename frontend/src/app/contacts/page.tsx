"use client";

import React, { useState, useMemo, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import { StatusText } from "@/components/ui/StatusText";
import {
  Search,
  Check,
  ChevronDown,
  ArrowLeft,
  X,
  Phone,
  Mail,
  MapPin,
  Clock,
  Wrench,
  Star,
  FileText,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  Building,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_CONTACTS, ContactItem, ContactCategory } from "@/data/contactsMockData";
import { DocumentViewerModal, DocumentItem } from "@/components/ui/DocumentViewerModal";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";

function ContactsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL state synchronization: ?contact=id
  const contactParam = searchParams.get("contact");

  const [activeTab, setActiveTab] = useState<"all" | "contractors" | "tenants">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedContactId, setSelectedContactId] = useState<string>(
    contactParam || MOCK_CONTACTS[0].id
  );
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);
  const [activePreviewDoc, setActivePreviewDoc] = useState<DocumentItem | null>(null);

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

  // Filtered contacts list
  const filteredContacts = useMemo(() => {
    return MOCK_CONTACTS.filter((contact) => {
      // Tab filter
      if (activeTab === "contractors" && contact.category !== "contractor") return false;
      if (activeTab === "tenants" && contact.category !== "tenant") return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = contact.name.toLowerCase().includes(q);
        const matchesCompany = (contact.companyName || "").toLowerCase().includes(q);
        const matchesTrade = contact.tradeOrRole.toLowerCase().includes(q);
        const matchesPhone = contact.phone.toLowerCase().includes(q);
        const matchesEmail = contact.email.toLowerCase().includes(q);
        if (!matchesName && !matchesCompany && !matchesTrade && !matchesPhone && !matchesEmail) {
          return false;
        }
      }
      return true;
    });
  }, [activeTab, searchQuery]);

  // Counts
  const stats = useMemo(() => {
    const total = MOCK_CONTACTS.length;
    const contractors = MOCK_CONTACTS.filter((c) => c.category === "contractor").length;
    const tenants = MOCK_CONTACTS.filter((c) => c.category === "tenant").length;
    return { total, contractors, tenants };
  }, []);

  const handleSelectContact = (contact: ContactItem) => {
    setSelectedContactId(contact.id);
    router.push(`/contacts?contact=${contact.id}`);
  };

  const handleMobileBack = () => {
    router.push("/contacts");
  };

  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
  const isMobileDetailScreen = Boolean(contactParam && isMobile);

  return (
    <div className="h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
        <TopCommandBar
          pageTitle="Contacts"
          hideSearch={true}
        />

        {/* ------------------------------------------------------------- */}
        {/* DESKTOP LAYOUT (>= 768px): List on Left + Detail on Right    */}
        {/* Left Column: 400px (Tabs + Search + Row list)                 */}
        {/* Right Column: flex-1 (Flat detail + Documents + Sticky Footer)*/}
        {/* ------------------------------------------------------------- */}
        <div className="hidden md:flex flex-1 overflow-hidden">
          
          {/* COLUMN 1: List (400px) */}
          <div className="w-[400px] shrink-0 border-r border-[var(--line)] bg-[var(--pane)] flex flex-col">
            
            {/* Header: Controls (Max 3 tabs, 1 search bar, no cards in cards) */}
            <div className="p-4 border-b border-[var(--line)] space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-[17px] font-heading font-semibold text-[var(--ink)] tracking-tight">
                    Contact Directory
                  </h2>
                  <div className="text-[12px] text-[var(--ink-3)] font-mono">
                    {stats.total} total · {stats.contractors} contractors · {stats.tenants} tenants
                  </div>
                </div>
              </div>

              {/* 3 Tabs */}
              <div className="inline-flex w-full rounded-lg border border-[var(--line)] p-0.5 bg-[var(--bg)] text-xs">
                <button
                  onClick={() => setActiveTab("all")}
                  className={cn(
                    "flex-1 py-1 rounded-md font-medium transition-colors cursor-pointer text-center",
                    activeTab === "all"
                      ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                      : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                  )}
                >
                  All ({stats.total})
                </button>
                <button
                  onClick={() => setActiveTab("contractors")}
                  className={cn(
                    "flex-1 py-1 rounded-md font-medium transition-colors cursor-pointer text-center",
                    activeTab === "contractors"
                      ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                      : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                  )}
                >
                  Contractors ({stats.contractors})
                </button>
                <button
                  onClick={() => setActiveTab("tenants")}
                  className={cn(
                    "flex-1 py-1 rounded-md font-medium transition-colors cursor-pointer text-center",
                    activeTab === "tenants"
                      ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                      : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                  )}
                >
                  Tenants ({stats.tenants})
                </button>
              </div>

              {/* 1 Search Input */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search name, trade, company, phone..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ink-3)] hover:text-[var(--ink)]"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            {/* List Rows */}
            <div className="flex-1 overflow-y-auto divide-y divide-[var(--line)]/60">
              {filteredContacts.map((contact) => {
                const isSelected = contact.id === activeContact?.id;

                return (
                  <button
                    key={contact.id}
                    onClick={() => handleSelectContact(contact)}
                    className={cn(
                      "w-full text-left p-3.5 transition-colors relative flex flex-col gap-1 cursor-pointer select-none",
                      isSelected
                        ? "bg-[var(--selected)] border-l-[3px] border-l-[var(--ink)]"
                        : "hover:bg-[var(--selected)]/40 border-l-[3px] border-l-transparent"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[14px] font-semibold text-[var(--ink)] truncate">
                        {contact.name}
                      </span>
                      {contact.openTicketsCount > 0 ? (
                        <span className="text-[11px] font-semibold text-[var(--accent-ink)] shrink-0">
                          {contact.openTicketsCount} open
                        </span>
                      ) : (
                        <span className="text-[11px] text-[var(--ink-3)] shrink-0">
                          Idle
                        </span>
                      )}
                    </div>

                    <div className="text-[12px] text-[var(--ink-2)] truncate">
                      {contact.companyName ? `${contact.companyName} · ` : ""}
                      {contact.tradeOrRole}
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-[var(--ink-3)] font-mono pt-0.5">
                      <span>{contact.phone}</span>
                      {contact.slaAvgHours ? (
                        <span>~{contact.slaAvgHours}h avg SLA</span>
                      ) : (
                        <span className="capitalize">{contact.category}</span>
                      )}
                    </div>
                  </button>
                );
              })}

              {filteredContacts.length === 0 && (
                <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                  No contacts match your search filter.
                </div>
              )}
            </div>
          </div>

          {/* COLUMN 2: Detail Pane (flex-1) with Sticky Footer */}
          {activeContact && (
            <div className="flex-1 bg-[var(--pane)] flex flex-col justify-between overflow-hidden">
              
              {/* Detail Content (Scrollable) */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-4xl">
                
                {/* Header */}
                <div className="border-b border-[var(--line)] pb-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h2 className="text-[22px] font-heading font-bold text-[var(--ink)] tracking-tight">
                        {activeContact.name}
                      </h2>
                      <p className="text-[14px] text-[var(--ink-2)] mt-0.5 font-medium">
                        {activeContact.companyName ? `${activeContact.companyName} · ` : ""}
                        {activeContact.tradeOrRole}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {activeContact.rating && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-[var(--selected)] border border-[var(--line)]">
                          <Star className="w-3.5 h-3.5 fill-[var(--ink)] text-[var(--ink)]" />
                          <span>{activeContact.rating}</span>
                        </span>
                      )}
                      <StatusText status={activeContact.status} />
                    </div>
                  </div>
                </div>

                {/* Plain 2-column key/value rows (Section 5.5: Zero cards in cards) */}
                <div className="space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Contact Specifications
                  </span>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6 text-xs">
                    <div>
                      <span className="text-[var(--ink-3)] block">Category</span>
                      <span className="font-medium text-[var(--ink)] capitalize">
                        {activeContact.category}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Trade / Role</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeContact.tradeOrRole}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Preferred Channel</span>
                      <span className="font-medium text-[var(--ink)] capitalize">
                        {activeContact.preferredChannel}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Average SLA Response</span>
                      <span className="font-mono text-sm font-semibold text-[var(--ink)]">
                        {activeContact.slaAvgHours ? `${activeContact.slaAvgHours} hours` : "N/A"}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Active Open Work Orders</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeContact.openTicketsCount > 0 ? (
                          <span className="text-[var(--accent-ink)] font-semibold">
                            {activeContact.openTicketsCount} tickets
                          </span>
                        ) : (
                          "0 tickets"
                        )}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Vetting / Insurance</span>
                      <span className="font-medium text-emerald-600 flex items-center gap-1 pt-0.5">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        <span>Verified & Insured</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Direct Communications Info */}
                <div className="border-t border-[var(--line)] pt-5 space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Communication Coordinates
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="flex items-center gap-2 text-[var(--ink)]">
                      <Phone className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                      <span className="font-mono">{activeContact.phone}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[var(--ink)]">
                      <Mail className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                      <span>{activeContact.email}</span>
                    </div>
                    {activeContact.address && (
                      <div className="flex items-center gap-2 text-[var(--ink-2)] sm:col-span-2">
                        <MapPin className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                        <span>{activeContact.address}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Notes (Plain text italic, no box) */}
                {activeContact.notes && (
                  <div className="border-t border-[var(--line)] pt-5 space-y-1">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                      Operations Notes
                    </span>
                    <p className="text-xs text-[var(--ink-2)] italic leading-relaxed">
                      {activeContact.notes}
                    </p>
                  </div>
                )}

                {/* Documents / Service Agreements (Section 5.6.1: 640px dialog on desktop / Full-screen viewer on mobile) */}
                <div className="border-t border-[var(--line)] pt-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                      Agreements & Certificates ({activeContact.documents.length})
                    </span>
                    <span className="text-[11px] text-[var(--ink-3)]">
                      Tap document to preview
                    </span>
                  </div>

                  <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-lg overflow-hidden bg-[var(--pane)]">
                    {activeContact.documents.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => setActivePreviewDoc(doc)}
                        className="p-3.5 flex items-center justify-between hover:bg-[var(--selected)]/50 transition-colors cursor-pointer select-none"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <FileText className="w-4 h-4 text-[var(--ink-2)] shrink-0" />
                          <div className="min-w-0">
                            <span className="text-xs font-semibold text-[var(--ink)] block truncate">
                              {doc.title}
                            </span>
                            <span className="text-[11px] text-[var(--ink-3)] block">
                              {doc.date} · {doc.size} {doc.pages ? `· ${doc.pages} pages` : ""}
                            </span>
                          </div>
                        </div>

                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setActivePreviewDoc(doc);
                          }}
                          className="text-xs border border-[var(--line)]"
                        >
                          Preview
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>

              </div>

              {/* Sticky Footer: One primary orange action only if AI proposal exists, otherwise ghost (Section 5.5) */}
              <div className="p-4 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-3 shrink-0">
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeContact.name)}`)}
                    className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                  >
                    View messages
                  </Button>
                  {activeContact.openTicketsCount > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeContact.name)}`)}
                      className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                    >
                      Active tickets ({activeContact.openTicketsCount})
                    </Button>
                  )}
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeContact.name)}`)}
                  className="text-xs border border-[var(--line)]"
                >
                  Direct message
                </Button>
              </div>

            </div>
          )}
        </div>

        {/* ------------------------------------------------------------- */}
        {/* MOBILE LAYOUT (< 768px): List then Full Detail Screen          */}
        {/* Screen 1: Contacts List (when ?contact is not in URL)         */}
        {/* Screen 2: Contact Detail Screen (when ?contact=id is in URL)  */}
        {/* ------------------------------------------------------------- */}
        <div className="md:hidden flex-1 flex flex-col min-w-0">

          {/* SCREEN 1: Mobile Contacts List */}
          {!isMobileDetailScreen && (
            <div className="flex-1 flex flex-col bg-[var(--bg)] pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
              {/* Header stats */}
              <div className="p-4 border-b border-[var(--line)] bg-[var(--pane)] space-y-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                  Contacts Directory
                </span>
                <div className="text-[14px] text-[var(--ink)] font-semibold">
                  {stats.total} Partners & Contractors
                </div>
                <div className="text-xs text-[var(--ink-3)]">
                  {stats.contractors} contractors · {stats.tenants} tenants
                </div>
              </div>

              {/* Controls: Scrollable Tabs + Search input */}
              <div className="p-3 border-b border-[var(--line)] bg-[var(--pane)] space-y-2">
                <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar text-xs">
                  <button
                    onClick={() => setActiveTab("all")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "all"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    All ({stats.total})
                  </button>
                  <button
                    onClick={() => setActiveTab("contractors")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "contractors"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Contractors ({stats.contractors})
                  </button>
                  <button
                    onClick={() => setActiveTab("tenants")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "tenants"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Tenants ({stats.tenants})
                  </button>
                </div>

                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--ink-3)]" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search name, trade, company..."
                    className="w-full pl-8 pr-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
                  />
                </div>
              </div>

              {/* Mobile Rows List (Section 5.6: List rows at least 64px tall, two lines) */}
              <div className="divide-y divide-[var(--line)] bg-[var(--pane)]">
                {filteredContacts.map((contact) => (
                  <button
                    key={contact.id}
                    onClick={() => handleSelectContact(contact)}
                    className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer select-none min-h-[64px]"
                  >
                    <div className="min-w-0 flex-1 pr-3">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-[15px] text-[var(--ink)] truncate">
                          {contact.name}
                        </span>
                        {contact.openTicketsCount > 0 ? (
                          <span className="text-xs font-semibold text-[var(--accent-ink)] shrink-0">
                            {contact.openTicketsCount} open
                          </span>
                        ) : (
                          <span className="text-xs text-[var(--ink-3)] shrink-0">
                            Idle
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--ink-3)] mt-0.5 truncate">
                        {contact.companyName ? `${contact.companyName} · ` : ""}
                        {contact.tradeOrRole}
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0 ml-1" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* SCREEN 2: Mobile Contact Detail Screen */}
          {isMobileDetailScreen && activeContact && (
            <div className="flex-1 flex flex-col bg-[var(--pane)] h-full">
              {/* Header with Back Arrow to Contacts List */}
              <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    onClick={handleMobileBack}
                    className="p-1 -ml-1 text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer"
                    aria-label="Back to contacts list"
                  >
                    <ArrowLeft className="w-5 h-5" />
                  </button>
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-bold text-[var(--ink)] truncate">
                      {activeContact.name}
                    </h2>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {activeContact.tradeOrRole}
                    </p>
                  </div>
                </div>

                <StatusText status={activeContact.status} />
              </div>

              {/* Scrollable Contact Profile */}
              <div className="flex-1 overflow-y-auto p-4 space-y-5">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                    Details
                  </span>
                  <div className="grid grid-cols-2 gap-y-3 text-sm">
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Role / Trade</span>
                      <span className="font-medium text-[var(--ink)]">{activeContact.tradeOrRole}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Category</span>
                      <span className="font-medium text-[var(--ink)] capitalize">{activeContact.category}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Avg SLA</span>
                      <span className="font-mono font-semibold text-[var(--ink)]">
                        {activeContact.slaAvgHours ? `${activeContact.slaAvgHours}h` : "N/A"}
                      </span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Active Tickets</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeContact.openTicketsCount > 0 ? (
                          <span className="text-[var(--accent-ink)] font-semibold">
                            {activeContact.openTicketsCount} tickets
                          </span>
                        ) : (
                          "0 tickets"
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Direct Communications */}
                <div className="border-t border-[var(--line)] pt-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-2">
                    Direct Contact
                  </span>
                  <div className="space-y-1.5 text-xs text-[var(--ink)]">
                    <div className="flex items-center gap-2">
                      <Phone className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                      <span className="font-mono">{activeContact.phone}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                      <span>{activeContact.email}</span>
                    </div>
                    {activeContact.address && (
                      <div className="flex items-center gap-2 text-[var(--ink-2)]">
                        <MapPin className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" />
                        <span>{activeContact.address}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Notes */}
                {activeContact.notes && (
                  <div className="border-t border-[var(--line)] pt-3">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                      Notes
                    </span>
                    <p className="text-xs text-[var(--ink-2)] italic leading-relaxed">
                      {activeContact.notes}
                    </p>
                  </div>
                )}

                {/* Filed Documents (Full-screen preview on mobile per Section 5.6.1) */}
                <div className="border-t border-[var(--line)] pt-3 space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Agreements ({activeContact.documents.length})
                  </span>

                  <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-lg overflow-hidden bg-[var(--pane)]">
                    {activeContact.documents.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => setActivePreviewDoc(doc)}
                        className="p-3 flex items-center justify-between hover:bg-[var(--selected)]/50 active:bg-[var(--selected)] transition-colors cursor-pointer select-none"
                      >
                        <div className="flex items-center gap-2.5 min-w-0 pr-2">
                          <FileText className="w-4 h-4 text-[var(--ink-2)] shrink-0" />
                          <div className="min-w-0">
                            <span className="text-xs font-semibold text-[var(--ink)] block truncate">
                              {doc.title}
                            </span>
                            <span className="text-[11px] text-[var(--ink-3)] block">
                              {doc.date} · {doc.size}
                            </span>
                          </div>
                        </div>

                        <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Sticky Footer: Sits at the very bottom above home indicator */}
              <div className="p-3 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-2 shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeContact.name)}`)}
                  className="flex-1 text-xs border border-[var(--line)] py-2.5"
                >
                  Messages
                </Button>
                {activeContact.openTicketsCount > 0 ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeContact.name)}`)}
                    className="flex-1 text-xs border border-[var(--line)] py-2.5"
                  >
                    Tickets ({activeContact.openTicketsCount})
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeContact.name)}`)}
                    className="flex-1 text-xs border border-[var(--line)] py-2.5"
                  >
                    Direct message
                  </Button>
                )}
              </div>
            </div>
          )}

        </div>

      </div>

      {/* 3. Mobile Bottom Tab Bar - Hidden on full Contact Detail Screen */}
      {!isMobileDetailScreen && <MobileTabBar />}

      {/* 4. Full-screen on mobile / 640px dialog on desktop Document Viewer (Section 5.6.1) */}
      <DocumentViewerModal
        document={activePreviewDoc}
        onClose={() => setActivePreviewDoc(null)}
        entityName={activeContact?.name}
      />

      {/* 5. Ask EstateOS Side Panel */}
      <AskEstateOSPanel
        currentPageName="Contacts"
        selectedContext={
          activeContact
            ? `Contact: ${activeContact.name} (${activeContact.tradeOrRole})`
            : "Contacts Directory"
        }
      />
    </div>
  );
}

export default function ContactsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Contacts...</div>}>
      <ContactsContent />
    </Suspense>
  );
}
