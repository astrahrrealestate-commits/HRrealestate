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
  Calendar,
  FileText,
  AlertTriangle,
  ChevronRight,
  ExternalLink,
  ShieldCheck,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_TENANTS, TenantProfile } from "@/data/tenantsMockData";
import { DocumentViewerModal, DocumentItem } from "@/components/ui/DocumentViewerModal";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";

function findMatchingTenant(allTenants: TenantProfile[], query: string): TenantProfile | null {
  if (!query) return null;
  const q = query.trim().toLowerCase();
  if (!q) return null;

  // 1. Exact ID match
  const exactId = allTenants.find((t) => t.id.toLowerCase() === q);
  if (exactId) return exactId;

  // 2. Name match (exact or substring)
  const byName = allTenants.find((t) => t.name.toLowerCase().includes(q));
  if (byName) return byName;

  // 3. Unit label, email or phone match
  const byUnit = allTenants.find(
    (t) =>
      t.unitLabel.toLowerCase().includes(q) ||
      t.email.toLowerCase().includes(q) ||
      (q.replace(/[^0-9]/g, "").length >= 4 &&
        t.phone.replace(/[^0-9]/g, "").includes(q.replace(/[^0-9]/g, "")))
  );
  if (byUnit) return byUnit;

  return null;
}

function TenantsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const superAgent = useSuperAgent();

  // URL state synchronization: ?tenant=id
  const tenantParam = searchParams.get("tenant");

  const [activeTab, setActiveTab] = useState<"all" | "up_to_date" | "overdue">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTenantId, setSelectedTenantId] = useState<string>(
    tenantParam || MOCK_TENANTS[0].id
  );
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);
  const [activePreviewDoc, setActivePreviewDoc] = useState<DocumentItem | null>(null);

  // Sync state if URL changes
  useEffect(() => {
    if (tenantParam) {
      const matched = findMatchingTenant(MOCK_TENANTS, tenantParam);
      if (matched) {
        setSelectedTenantId(matched.id);
        if (matched.rentStatus === "overdue" && activeTab === "up_to_date") {
          setActiveTab("overdue");
        } else if (matched.rentStatus === "up_to_date" && activeTab === "overdue") {
          setActiveTab("up_to_date");
        }
      }
    }
  }, [tenantParam, activeTab]);

  // Listen for instant custom navigation events (handles same-page Super Agent clicks)
  useEffect(() => {
    const handleCustomNav = (e: Event) => {
      const customEvent = e as CustomEvent<{ url: string }>;
      const url = customEvent?.detail?.url;
      if (url && url.includes("/tenants")) {
        const match = url.match(/[?&]tenant=([^&]+)/);
        if (match) {
          const target = decodeURIComponent(match[1]);
          const matched = findMatchingTenant(MOCK_TENANTS, target);
          if (matched) {
            setSelectedTenantId(matched.id);
            if (matched.rentStatus === "overdue" && activeTab === "up_to_date") {
              setActiveTab("overdue");
            } else if (matched.rentStatus === "up_to_date" && activeTab === "overdue") {
              setActiveTab("up_to_date");
            }
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, [activeTab]);

  // Derived active tenant
  const activeTenant = useMemo(() => {
    return (
      findMatchingTenant(MOCK_TENANTS, selectedTenantId) ||
      MOCK_TENANTS[0]
    );
  }, [selectedTenantId]);

  useEffect(() => {
    superAgent.setCurrentPageName("Tenants");
    if (activeTenant) {
      superAgent.setSelectedContext(
        `Tenant: ${activeTenant.name} (${activeTenant.unitLabel}) [Status: ${activeTenant.rentStatus}, Rent: € ${activeTenant.monthlyRentEur}/mo, Phone: ${activeTenant.phone}]`
      );
    } else {
      superAgent.setSelectedContext("Tenant Directory (110 active tenants)");
    }
  }, [activeTenant, superAgent.setCurrentPageName, superAgent.setSelectedContext]);

  // Filtered tenants list
  const filteredTenants = useMemo(() => {
    return MOCK_TENANTS.filter((tenant) => {
      // Tab filter
      if (activeTab === "up_to_date" && tenant.rentStatus !== "up_to_date") return false;
      if (activeTab === "overdue" && tenant.rentStatus !== "overdue" && tenant.rentStatus !== "grace_period") return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesName = tenant.name.toLowerCase().includes(q);
        const matchesUnit = tenant.unitLabel.toLowerCase().includes(q);
        const matchesEmail = tenant.email.toLowerCase().includes(q);
        const matchesPhone = tenant.phone.toLowerCase().includes(q);
        if (!matchesName && !matchesUnit && !matchesEmail && !matchesPhone) {
          return false;
        }
      }
      return true;
    });
  }, [activeTab, searchQuery]);

  // Aggregate stats
  const stats = useMemo(() => {
    const total = MOCK_TENANTS.length;
    const overdue = MOCK_TENANTS.filter((t) => t.rentStatus === "overdue").length;
    const upToDate = total - overdue;
    return { total, overdue, upToDate };
  }, []);

  const handleSelectTenant = (tenant: TenantProfile) => {
    setSelectedTenantId(tenant.id);
    router.push(`/tenants?tenant=${tenant.id}`);
  };

  const handleMobileBack = () => {
    router.push("/tenants");
  };

  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
  const isMobileDetailScreen = Boolean(tenantParam && isMobile);

  return (
    <div className="h-dvh bg-[#1B1B1B] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#1B1B1B]">
        <TopCommandBar
          pageTitle="Tenants"
          hideSearch={true}
        />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">

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
                    Tenant Directory
                  </h2>
                  <div className="text-[12px] text-[var(--ink-3)] font-mono">
                    {stats.total} total · {stats.overdue} overdue · {stats.upToDate} up to date
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
                  onClick={() => setActiveTab("up_to_date")}
                  className={cn(
                    "flex-1 py-1 rounded-md font-medium transition-colors cursor-pointer text-center",
                    activeTab === "up_to_date"
                      ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                      : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                  )}
                >
                  Paid ({stats.upToDate})
                </button>
                <button
                  onClick={() => setActiveTab("overdue")}
                  className={cn(
                    "flex-1 py-1 rounded-md font-medium transition-colors cursor-pointer text-center",
                    activeTab === "overdue"
                      ? "bg-[var(--pane)] text-[var(--accent-ink)] shadow-2xs font-semibold"
                      : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                  )}
                >
                  Overdue ({stats.overdue})
                </button>
              </div>

              {/* 1 Search Input */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search tenant name, unit, phone..."
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
              {filteredTenants.map((tenant) => {
                const isSelected = tenant.id === activeTenant?.id;
                const isOverdue = tenant.rentStatus === "overdue";

                return (
                  <button
                    key={tenant.id}
                    onClick={() => handleSelectTenant(tenant)}
                    className={cn(
                      "w-full text-left p-3.5 transition-colors relative flex flex-col gap-1 cursor-pointer",
                      isSelected
                        ? "bg-[var(--selected)] border-l-[3px] border-l-[var(--ink)]"
                        : "hover:bg-[var(--selected)]/40 border-l-[3px] border-l-transparent"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[14px] font-semibold text-[var(--ink)] truncate">
                        {tenant.name}
                      </span>
                      {isOverdue ? (
                        <span className="text-[11px] font-semibold text-[var(--accent-ink)] shrink-0">
                          {tenant.overdueDays}d overdue
                        </span>
                      ) : (
                        <span className="text-[11px] text-[var(--ink-3)] shrink-0">
                          Paid
                        </span>
                      )}
                    </div>

                    <div className="text-[12px] text-[var(--ink-2)] truncate">
                      {tenant.unitLabel}
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-[var(--ink-3)] font-mono pt-0.5">
                      <span>€ {tenant.monthlyRentEur},- / mo</span>
                      <span>Lease: {tenant.leaseEnd}</span>
                    </div>
                  </button>
                );
              })}

              {filteredTenants.length === 0 && (
                <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                  No tenants match your search filter.
                </div>
              )}
            </div>
          </div>

          {/* COLUMN 2: Detail Pane (flex-1) with Sticky Footer */}
          {activeTenant && (
            <div className="flex-1 bg-[var(--pane)] flex flex-col justify-between overflow-hidden">

              {/* Detail Content (Scrollable) */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-4xl">

                {/* Header */}
                <div className="border-b border-[var(--line)] pb-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h2 className="text-[22px] font-heading font-bold text-[var(--ink)] tracking-tight">
                        {activeTenant.name}
                      </h2>
                      <p className="text-[14px] text-[var(--ink-2)] mt-0.5 font-medium">
                        {activeTenant.unitLabel} · {activeTenant.complexName}
                      </p>
                    </div>

                    <div>
                      {activeTenant.rentStatus === "overdue" ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-semibold bg-[var(--accent)]/15 text-[var(--accent-ink)] border border-[var(--accent)]/30">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          <span>{activeTenant.overdueDays} Days Overdue (€ {activeTenant.overdueAmountEur},-)</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium text-[var(--ink-2)] bg-[var(--selected)] border border-[var(--line)]">
                          <span>Rent Up to Date</span>
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Plain 2-column key/value rows (Section 5.5: Zero cards in cards) */}
                <div className="space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Lease & Tenancy Specs
                  </span>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-y-3 gap-x-6 text-xs">
                    <div>
                      <span className="text-[var(--ink-3)] block">Monthly Rent</span>
                      <span className="font-mono text-sm font-semibold text-[var(--ink)]">
                        € {activeTenant.monthlyRentEur},-
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Security Deposit</span>
                      <span className="font-mono text-sm text-[var(--ink-2)]">
                        € {activeTenant.depositEur},-
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Lease Commencement</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeTenant.leaseStart}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Lease Expiry</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeTenant.leaseEnd}
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Identity & Vetting</span>
                      <span className="font-medium text-emerald-600 flex items-center gap-1 pt-0.5">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        <span>iDIN Verified</span>
                      </span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">Payment Status</span>
                      <span className="font-medium text-[var(--ink)]">
                        {activeTenant.rentStatus === "overdue" ? (
                          <span className="text-[var(--accent-ink)] font-semibold">Overdue ({activeTenant.overdueDays}d)</span>
                        ) : (
                          "Direct Debit (SEPA)"
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Direct Contact Channels */}
                <div className="border-t border-[var(--line)] pt-5 space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Contact Channels
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                    <div className="flex items-center gap-2 text-[var(--ink)]">
                      <Phone className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                      <span className="font-mono">{activeTenant.phone}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[var(--ink)]">
                      <Mail className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                      <span>{activeTenant.email}</span>
                    </div>
                  </div>
                </div>

                {/* Notes (Plain text italic, no box) */}
                {activeTenant.notes && (
                  <div className="border-t border-[var(--line)] pt-5 space-y-1">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                      Case & Tenancy Notes
                    </span>
                    <p className="text-xs text-[var(--ink-2)] italic leading-relaxed">
                      {activeTenant.notes}
                    </p>
                  </div>
                )}

                {/* Documents List (Section 5.6.1: 640px dialog on desktop / Full-screen viewer on mobile) */}
                <div className="border-t border-[var(--line)] pt-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                      Filed Documents ({activeTenant.documents.length})
                    </span>
                    <span className="text-[11px] text-[var(--ink-3)]">
                      Tap document to preview
                    </span>
                  </div>

                  <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-lg overflow-hidden bg-[var(--pane)]">
                    {activeTenant.documents.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => setActivePreviewDoc(doc)}
                        className="p-3.5 flex items-center justify-between hover:bg-[var(--selected)]/50 transition-colors cursor-pointer"
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
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeTenant.name)}`)}
                    className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                  >
                    View messages
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/properties?complex=comp-keizersgracht`)}
                    className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                  >
                    View unit
                  </Button>
                </div>

                {activeTenant.rentStatus === "overdue" ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeTenant.name)}`)}
                    className="text-xs bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-black font-semibold"
                  >
                    ✦ Send rent reminder
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeTenant.name)}`)}
                    className="text-xs border border-[var(--line)]"
                  >
                    Contact tenant
                  </Button>
                )}
              </div>

            </div>
          )}
        </div>

        {/* ------------------------------------------------------------- */}
        {/* MOBILE LAYOUT (< 768px): List then Full Detail Screen          */}
        {/* Screen 1: Tenants List (when ?tenant is not in URL)           */}
        {/* Screen 2: Tenant Detail Screen (when ?tenant=id is in URL)    */}
        {/* ------------------------------------------------------------- */}
        <div className="md:hidden flex-1 flex flex-col min-w-0">

          {/* SCREEN 1: Mobile Tenants List */}
          {!isMobileDetailScreen && (
            <div className="flex-1 flex flex-col bg-[var(--bg)] pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
              {/* Header stats */}
              <div className="p-4 border-b border-[var(--line)] bg-[var(--pane)] space-y-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                  Tenant Directory
                </span>
                <div className="text-[14px] text-[var(--ink)] font-semibold">
                  {stats.total} Active Residents
                </div>
                <div className="text-xs text-[var(--ink-3)]">
                  {stats.overdue} overdue · {stats.upToDate} up to date
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
                    onClick={() => setActiveTab("up_to_date")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "up_to_date"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Paid ({stats.upToDate})
                  </button>
                  <button
                    onClick={() => setActiveTab("overdue")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "overdue"
                        ? "bg-[var(--accent)] text-black font-semibold"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Overdue ({stats.overdue})
                  </button>
                </div>

                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--ink-3)]" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search tenant name or unit..."
                    className="w-full pl-8 pr-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
                  />
                </div>
              </div>

              {/* Mobile Rows List (Section 5.6: List rows at least 64px tall, two lines) */}
              <div className="divide-y divide-[var(--line)] bg-[var(--pane)]">
                {filteredTenants.map((tenant) => (
                  <button
                    key={tenant.id}
                    onClick={() => handleSelectTenant(tenant)}
                    className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer min-h-[64px]"
                  >
                    <div className="min-w-0 flex-1 pr-3">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-[15px] text-[var(--ink)] truncate">
                          {tenant.name}
                        </span>
                        {tenant.rentStatus === "overdue" ? (
                          <span className="text-xs font-semibold text-[var(--accent-ink)] shrink-0">
                            {tenant.overdueDays}d overdue
                          </span>
                        ) : (
                          <span className="text-xs text-[var(--ink-3)] shrink-0">
                            Paid
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[var(--ink-3)] mt-0.5 truncate">
                        {tenant.unitLabel} · € {tenant.monthlyRentEur},-
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0 ml-1" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* SCREEN 2: Mobile Tenant Detail Screen */}
          {isMobileDetailScreen && activeTenant && (
            <div className="flex-1 flex flex-col bg-[var(--pane)] h-full">
              {/* Header with Back Arrow to Tenants List */}
              <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    onClick={handleMobileBack}
                    className="p-1 -ml-1 text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer"
                    aria-label="Back to tenant list"
                  >
                    <ArrowLeft className="w-5 h-5" />
                  </button>
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-bold text-[var(--ink)] truncate">
                      {activeTenant.name}
                    </h2>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {activeTenant.unitLabel}
                    </p>
                  </div>
                </div>

                {activeTenant.rentStatus === "overdue" ? (
                  <span className="text-xs font-semibold text-[var(--accent-ink)]">
                    {activeTenant.overdueDays}d overdue
                  </span>
                ) : (
                  <span className="text-xs text-[var(--ink-3)]">
                    Paid
                  </span>
                )}
              </div>

              {/* Scrollable Tenant Profile */}
              <div className="flex-1 overflow-y-auto p-4 space-y-5">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                    Lease Specs
                  </span>
                  <div className="grid grid-cols-2 gap-y-3 text-sm">
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Monthly Rent</span>
                      <span className="font-mono font-semibold text-[var(--ink)]">
                        € {activeTenant.monthlyRentEur},-
                      </span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Security Deposit</span>
                      <span className="font-mono text-[var(--ink-2)]">
                        € {activeTenant.depositEur},-
                      </span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Commencement</span>
                      <span className="font-medium text-[var(--ink)]">{activeTenant.leaseStart}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Expiry</span>
                      <span className="font-medium text-[var(--ink)]">{activeTenant.leaseEnd}</span>
                    </div>
                  </div>
                </div>

                {/* Contact Information */}
                <div className="border-t border-[var(--line)] pt-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-2">
                    Direct Contact
                  </span>
                  <div className="space-y-1.5 text-xs text-[var(--ink)]">
                    <div className="flex items-center gap-2">
                      <Phone className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                      <span className="font-mono">{activeTenant.phone}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                      <span>{activeTenant.email}</span>
                    </div>
                  </div>
                </div>

                {/* Notes */}
                {activeTenant.notes && (
                  <div className="border-t border-[var(--line)] pt-3">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                      Notes
                    </span>
                    <p className="text-xs text-[var(--ink-2)] italic leading-relaxed">
                      {activeTenant.notes}
                    </p>
                  </div>
                )}

                {/* Filed Documents (Full-screen preview on mobile per Section 5.6.1) */}
                <div className="border-t border-[var(--line)] pt-3 space-y-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Documents ({activeTenant.documents.length})
                  </span>

                  <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-lg overflow-hidden bg-[var(--pane)]">
                    {activeTenant.documents.map((doc) => (
                      <div
                        key={doc.id}
                        onClick={() => setActivePreviewDoc(doc)}
                        className="p-3 flex items-center justify-between hover:bg-[var(--selected)]/50 active:bg-[var(--selected)] transition-colors cursor-pointer"
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
                  onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeTenant.name)}`)}
                  className="flex-1 text-xs border border-[var(--line)] py-2.5"
                >
                  Messages
                </Button>
                {activeTenant.rentStatus === "overdue" ? (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeTenant.name)}`)}
                    className="flex-1 text-xs bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-black font-semibold py-2.5"
                  >
                    ✦ Send reminder
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/properties?complex=comp-keizersgracht`)}
                    className="flex-1 text-xs border border-[var(--line)] py-2.5"
                  >
                    View unit
                  </Button>
                )}
              </div>
            </div>
          )}

        </div>
          </div>

          {/* Ask EstateOS Side Panel (40% width on right side) */}
          <AskEstateOSPanel
            currentPageName="Tenants"
            selectedContext={
              activeTenant
                ? `Tenant: ${activeTenant.name} (${activeTenant.unitLabel})`
                : "Tenants Directory"
            }
          />
        </div>
      </div>

      {/* 3. Mobile Bottom Tab Bar - Hidden on full Tenant Detail Screen */}
      {!isMobileDetailScreen && <MobileTabBar />}

      {/* 4. Full-screen on mobile / 640px dialog on desktop Document Viewer (Section 5.6.1) */}
      <DocumentViewerModal
        document={activePreviewDoc}
        onClose={() => setActivePreviewDoc(null)}
        entityName={activeTenant?.name}
        unitLabel={activeTenant?.unitLabel}
      />


    </div>
  );
}

export default function TenantsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Tenants...</div>}>
      <TenantsContent />
    </Suspense>
  );
}
