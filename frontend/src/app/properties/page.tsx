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
  Building2,
  Home,
  ShieldCheck,
  Phone,
  Mail,
  User,
  Calendar,
  Layers,
  ExternalLink,
  ChevronRight,
  Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { PropertyComplex, UnitDetail } from "@/types/portfolio";
import { getPortfolio } from "@/lib/portfolioApi";
import { euro, specLine, UNKNOWN } from "@/lib/portfolioFormat";
import { PageStateShell } from "@/components/portfolio/PageStateShell";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";

function findMatchingUnitAndComplex(
  complexes: PropertyComplex[],
  unitQuery?: string | null,
  complexQuery?: string | null
): { complex: PropertyComplex; unit: UnitDetail | null } | null {
  const uClean = (unitQuery || "").trim().toLowerCase();
  const cClean = (complexQuery || "").trim().toLowerCase();

  let searchPool = complexes;
  if (cClean) {
    const matchedComp = complexes.find(
      (c) => c.id.toLowerCase() === cClean || c.name.toLowerCase().includes(cClean)
    );
    if (matchedComp) {
      if (!uClean) {
        return { complex: matchedComp, unit: null };
      }
      searchPool = [matchedComp, ...complexes.filter((c) => c.id !== matchedComp.id)];
    }
  }

  if (!uClean) return null;

  for (const comp of searchPool) {
    const exact = comp.units.find(
      (u) =>
        u.id.toLowerCase() === uClean ||
        u.unitNumber.toLowerCase() === uClean ||
        u.fullAddress.toLowerCase() === uClean
    );
    if (exact) return { complex: comp, unit: exact };

    const partial = comp.units.find(
      (u) =>
        u.unitNumber.toLowerCase().includes(uClean) ||
        u.fullAddress.toLowerCase().includes(uClean) ||
        (u.currentTenant?.name && u.currentTenant.name.toLowerCase().includes(uClean))
    );
    if (partial) return { complex: comp, unit: partial };
  }

  return null;
}

function PropertiesView({ complexes: PROPERTY_COMPLEXES }: { complexes: PropertyComplex[] }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  // URL state synchronization: ?complex=comp-id&unit=unit-id
  const complexParam = searchParams.get("complex");
  const unitParam = searchParams.get("unit");

  const [activeTab, setActiveTab] = useState<"all" | "occupied" | "vacant">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedComplexId, setSelectedComplexId] = useState<string>(
    complexParam || PROPERTY_COMPLEXES[0].id
  );
  const [selectedUnitId, setSelectedUnitId] = useState<string | null>(unitParam || null);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);

  // Sync state if URL changes (e.g. deep links or browser navigation)
  useEffect(() => {
    if (unitParam || complexParam) {
      const result = findMatchingUnitAndComplex(PROPERTY_COMPLEXES, unitParam, complexParam);
      if (result) {
        setSelectedComplexId(result.complex.id);
        if (result.unit) {
          const matchedUnit = result.unit;
          setSelectedUnitId(matchedUnit.id);
          // Only a deep link may move the tab, and only when it would hide the linked unit. The tab itself must
          // not be a dependency, or clicking a tab re-runs this and snaps it back.
          setActiveTab((tab) => {
            if (matchedUnit.status === "occupied" && tab === "vacant") return "occupied";
            if (matchedUnit.status !== "occupied" && tab === "occupied") return "vacant";
            return tab;
          });
        } else {
          setSelectedUnitId(null);
        }
      } else if (complexParam && PROPERTY_COMPLEXES.some((c) => c.id === complexParam)) {
        setSelectedComplexId(complexParam);
        setSelectedUnitId(null);
      }
    } else {
      setSelectedUnitId(null);
    }
  }, [complexParam, unitParam, PROPERTY_COMPLEXES]);

  // Listen for instant custom navigation events (handles same-page Super Agent clicks)
  useEffect(() => {
    const handleCustomNav = (e: Event) => {
      const customEvent = e as CustomEvent<{ url: string }>;
      const url = customEvent?.detail?.url;
      if (url && url.includes("/properties")) {
        const uMatch = url.match(/[?&]unit=([^&]+)/);
        const cMatch = url.match(/[?&]complex=([^&]+)/);
        const u = uMatch ? decodeURIComponent(uMatch[1]) : "";
        const c = cMatch ? decodeURIComponent(cMatch[1]) : "";
        const result = findMatchingUnitAndComplex(PROPERTY_COMPLEXES, u, c);
        if (result) {
          setSelectedComplexId(result.complex.id);
          if (result.unit) {
            setSelectedUnitId(result.unit.id);
            if (result.unit.status === "occupied" && activeTab === "vacant") {
              setActiveTab("occupied");
            } else if (result.unit.status === "vacant" && activeTab === "occupied") {
              setActiveTab("vacant");
            }
          } else {
            setSelectedUnitId(null);
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, [activeTab, PROPERTY_COMPLEXES]);

  // Derived current complex and current unit
  const activeComplex = useMemo(() => {
    return (
      PROPERTY_COMPLEXES.find((c) => c.id === selectedComplexId) ||
      PROPERTY_COMPLEXES[0]
    );
  }, [selectedComplexId]);

  // If on desktop and no unit is selected, default to the first unit of active complex
  const activeUnit = useMemo(() => {
    if (selectedUnitId) {
      // Find unit in active complex or across all complexes
      for (const comp of PROPERTY_COMPLEXES) {
        const found = comp.units.find((u) => u.id === selectedUnitId);
        if (found) return found;
      }
    }
    return activeComplex.units[0] || null;
  }, [selectedUnitId, activeComplex]);

  useEffect(() => {
    superAgent.setCurrentPageName("Properties");
    if (activeUnit) {
      superAgent.setSelectedContext(
        `Property Unit: ${activeUnit.unitNumber} (${activeComplex.name}, ${activeUnit.fullAddress}) [Status: ${activeUnit.status}, Tenant: ${activeUnit.currentTenant?.name || "Vacant"}, Rent: € ${activeUnit.monthlyRentEur}/mo]`
      );
    } else {
      superAgent.setSelectedContext(`Complex: ${activeComplex.name} (${activeComplex.address})`);
    }
  }, [activeUnit, activeComplex, superAgent.setCurrentPageName, superAgent.setSelectedContext]);

  // Filtered units within active complex according to Tab and Search
  const filteredUnits = useMemo(() => {
    return activeComplex.units.filter((unit) => {
      // Tab filter
      if (activeTab === "occupied" && unit.status === "vacant") return false;
      if (activeTab === "vacant" && unit.status !== "vacant") return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesUnit = unit.unitNumber.toLowerCase().includes(q);
        const matchesAddress = unit.fullAddress.toLowerCase().includes(q);
        const matchesTenant = unit.currentTenant?.name.toLowerCase().includes(q);
        if (!matchesUnit && !matchesAddress && !matchesTenant) {
          return false;
        }
      }
      return true;
    });
  }, [activeComplex, activeTab, searchQuery]);

  // Portfolio-wide metrics
  const portfolioStats = useMemo(() => {
    let total = 0;
    let occupied = 0;
    let vacant = 0;
    let notice = 0;
    PROPERTY_COMPLEXES.forEach((c) => {
      total += c.totalUnits;
      occupied += c.occupiedUnits;
      vacant += c.vacantUnits;
      notice += c.noticeGivenUnits;
    });
    const rate = total === 0 ? UNKNOWN : `${Math.round((occupied / total) * 1000) / 10}%`;
    return { total, occupied, vacant, notice, rate };
  }, [PROPERTY_COMPLEXES]);

  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const sync = () => setIsMobile(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  // Complex switch handler
  const handleSelectComplex = (complexId: string) => {
    setSelectedComplexId(complexId);
    // When switching complex on mobile, we navigate to the complex screen (no unit auto-selected)
    const firstUnit = PROPERTY_COMPLEXES.find((c) => c.id === complexId)?.units[0]?.id;
    if (window.innerWidth < 768) {
      setSelectedUnitId(null);
      router.push(`/properties?complex=${complexId}`);
    } else {
      setSelectedUnitId(firstUnit || null);
      router.push(`/properties?complex=${complexId}&unit=${firstUnit || ""}`);
    }
  };

  // Unit select handler
  const handleSelectUnit = (unit: UnitDetail) => {
    setSelectedUnitId(unit.id);
    router.push(`/properties?complex=${unit.complexId}&unit=${unit.id}`);
  };

  // Back handler for mobile navigation stack
  const handleMobileBack = () => {
    if (unitParam || selectedUnitId) {
      // Back from Unit Screen to Complex Screen
      setSelectedUnitId(null);
      router.push(`/properties?complex=${selectedComplexId}`);
    } else if (complexParam) {
      // Back from Complex Screen to Complexes List
      router.push(`/properties`);
    }
  };


  // Mobile navigation view state: complex click opens Complex Screen; only explicit unit selection opens Unit Screen
  const isMobileUnitScreen = Boolean(unitParam || (selectedUnitId && isMobile));
  const isMobileComplexScreen = Boolean(complexParam && !isMobileUnitScreen);
  const isMobileComplexList = !isMobileComplexScreen && !isMobileUnitScreen;

  return (
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar
          pageTitle="Properties"
          hideSearch={true}
        />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#27272a] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">

        {/* ------------------------------------------------------------- */}
        {/* DESKTOP LAYOUT (>= 768px): 3 Columns                         */}
        {/* Col 1: Complex list (240px)                                   */}
        {/* Col 2: Unit grid (5 per row)                                  */}
        {/* Col 3: Unit detail pane (380px)                               */}
        {/* ------------------------------------------------------------- */}
        <div className="hidden md:flex flex-1 overflow-hidden min-w-0">

          {/* COLUMN 1: Complex List (Left pane, tightens smoothly when Super Agent is open) */}
          <div
            className={cn(
              "shrink-0 border-r border-[var(--line)] bg-[var(--pane)] flex flex-col",
              superAgent.isOpen ? "w-[175px] xl:w-[195px]" : "w-[200px] xl:w-[240px]"
            )}
          >
            <div className="p-3 xl:p-4 border-b border-[var(--line)]">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                {t("properties.complexes", "Portfolio Complexes")}
              </span>
              <div className="text-[12px] xl:text-[13px] text-[var(--ink-2)] font-mono">
                {portfolioStats.total} {t("properties.units_count", "units")} · {portfolioStats.rate} {t("properties.occupied_count", "occupied")}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-[var(--line)]/60">
              {PROPERTY_COMPLEXES.map((comp) => {
                const isSelected = comp.id === selectedComplexId;
                return (
                  <button
                    key={comp.id}
                    onClick={() => handleSelectComplex(comp.id)}
                    className={cn(
                      "w-full text-left p-3.5 transition-colors relative flex flex-col gap-1 cursor-pointer",
                      isSelected
                        ? "bg-[var(--selected)] border-l-[3px] border-l-[var(--ink)]"
                        : "hover:bg-[var(--selected)]/40 border-l-[3px] border-l-transparent"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[13px] font-semibold text-[var(--ink)] truncate">
                        {comp.name}
                      </span>
                      <span className="text-[11px] font-mono font-medium text-[var(--ink-3)] tabular-nums shrink-0">
                        {comp.occupiedUnits}/{comp.totalUnits}
                      </span>
                    </div>

                    <div className="text-[12px] text-[var(--ink-3)] truncate">
                      {comp.neighborhood ?? ""}
                    </div>

                    {/* Progress indicator */}
                    <div className="w-full bg-[var(--line)] h-1 rounded-full overflow-hidden mt-1">
                      <div
                        className="bg-[var(--ink)] h-full rounded-full transition-all"
                        style={{ width: `${comp.occupancyRate}%` }}
                      />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* COLUMN 2: Unit Grid 5 per row + Controls (Middle pane, flex-1) */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden bg-[var(--pane)] border-r border-[var(--line)]">
            {/* Header: Title + Inline Stats + Controls (Max 3 tabs, 1 search bar, no cards in cards) */}
            <div className="p-4 border-b border-[var(--line)] flex flex-col gap-3 min-w-0">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <h2 className="text-[17px] font-heading font-semibold text-[var(--ink)] tracking-tight truncate">
                    {activeComplex.name}
                  </h2>
                  <p className="text-[12px] text-[var(--ink-3)] leading-snug">
                    {activeComplex.address} · {activeComplex.occupiedUnits} occupied · {activeComplex.vacantUnits} vacant
                  </p>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeComplex.name)}`)}
                    className="text-xs border border-[var(--line)] text-[var(--ink-2)] whitespace-nowrap"
                  >
                    Complex tickets
                  </Button>
                </div>
              </div>

              {/* Controls bar: 3 Tabs (All / Occupied / Vacant) + Search input */}
              <div className="flex flex-wrap items-center justify-between gap-2 pt-1 min-w-0">
                {/* 3 Tabs */}
                <div className="inline-flex rounded-lg border border-[var(--line)] p-0.5 bg-[var(--bg)] text-xs shrink-0 max-w-full overflow-x-auto no-scrollbar">
                  <button
                    onClick={() => setActiveTab("all")}
                    className={cn(
                      "px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer whitespace-nowrap",
                      activeTab === "all"
                        ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                        : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                    )}
                  >
                    {t("All")} ({activeComplex.units.length})
                  </button>
                  <button
                    onClick={() => setActiveTab("occupied")}
                    className={cn(
                      "px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer whitespace-nowrap",
                      activeTab === "occupied"
                        ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                        : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                    )}
                  >
                    {t("Occupied")} ({activeComplex.units.filter((u) => u.status !== "vacant").length})
                  </button>
                  <button
                    onClick={() => setActiveTab("vacant")}
                    className={cn(
                      "px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer whitespace-nowrap",
                      activeTab === "vacant"
                        ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs font-semibold"
                        : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                    )}
                  >
                    {t("Vacant")} ({activeComplex.units.filter((u) => u.status === "vacant").length})
                  </button>
                </div>

                {/* Single Search Bar */}
                <div className="relative flex-1 min-w-[160px] max-w-full sm:max-w-[260px]">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)] pointer-events-none" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t("Search properties...", "Zoek eenheden...")}
                    className="w-full pl-8 pr-7 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
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
            </div>

            {/* UNIT GRID (Flexible auto-fit grid so cards never get squished or overlap) */}
            <div className="flex-1 p-3.5 xl:p-4 overflow-y-auto">
              <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2.5">
                {filteredUnits.map((unit) => {
                  const isUnitSelected = activeUnit?.id === unit.id;
                  const isVacant = unit.status === "vacant";
                  const isNotice = unit.status === "notice_given";

                  return (
                    <button
                      key={unit.id}
                      onClick={() => handleSelectUnit(unit)}
                      className={cn(
                        "relative p-2.5 rounded-[var(--radius-pane)] border transition-all text-left flex flex-col justify-between h-[112px] min-w-0 cursor-pointer",
                        isUnitSelected
                          ? "border-[var(--ink)] bg-[var(--selected)] shadow-2xs"
                          : "border-[var(--line)] bg-[var(--pane)] hover:border-[var(--ink-3)] hover:bg-[var(--selected)]/30"
                      )}
                    >
                      {/* Top: Unit badge / number + status indicator */}
                      <div className="flex items-start justify-between">
                        <div>
                          <span className="font-mono text-[14px] font-bold text-[var(--ink)] block">
                            {unit.unitNumber}
                          </span>
                          <span className="text-[11px] text-[var(--ink-3)] block truncate max-w-[90px]">
                            {specLine(unit.floor, unit.areaSqm)}
                          </span>
                        </div>

                        <span
                          className={cn(
                            "w-2 h-2 rounded-full shrink-0 mt-1",
                            unit.status === "occupied"
                              ? "bg-[var(--ink)]"
                              : isNotice
                              ? "bg-[var(--accent)]"
                              : "bg-[var(--line)] border border-[var(--ink-3)]"
                          )}
                          title={unit.status}
                        />
                      </div>

                      {/* Middle: Tenant name or Vacant label */}
                      <div className="min-w-0">
                        {unit.currentTenant ? (
                          <div className="text-[12px] font-medium text-[var(--ink)] truncate">
                            {unit.currentTenant.name}
                          </div>
                        ) : (
                          <div className="text-[12px] font-medium text-[var(--ink-3)] italic">
                            {unit.status === "vacant" ? "Vacant" : "Occupied · tenant not linked"}
                          </div>
                        )}
                        <div className="text-[11px] font-mono text-[var(--ink-3)] tabular-nums">
                          {euro(unit.monthlyRentEur)}
                        </div>
                      </div>

                      {/* Bottom: active ticket flag */}
                      <div className="flex items-center justify-between text-[10px] text-[var(--ink-3)] border-t border-[var(--line)]/50 pt-1 mt-1 font-mono">
                        <span />
                        {(unit.activeTicketCount ?? 0) > 0 && (
                          <span className="text-[var(--accent-ink)] font-semibold">
                            {unit.activeTicketCount} ticket
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>

              {filteredUnits.length === 0 && (
                <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                  No units match the filter criteria.
                </div>
              )}
            </div>
          </div>

          {/* COLUMN 3: Unit Detail Pane (Right pane, tightens smoothly when Super Agent is open) */}
          {activeUnit && (
            <div
              className={cn(
                "shrink-0 bg-[var(--pane)] flex flex-col justify-between border-l border-[var(--line)] min-w-0",
                superAgent.isOpen ? "w-[250px] xl:w-[290px]" : "w-[300px] xl:w-[350px]"
              )}
            >

              {/* Detail Content (Scrollable) */}
              <div className="flex-1 overflow-y-auto p-4 xl:p-5 space-y-4">
                {/* Header */}
                <div className="border-b border-[var(--line)] pb-4">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-[20px] font-bold text-[var(--ink)]">
                      Unit {activeUnit.unitNumber}
                    </span>
                    <StatusText status={activeUnit.status} />
                  </div>
                  <div className="text-[13px] text-[var(--ink-2)] mt-0.5">
                    {activeUnit.fullAddress}
                  </div>
                </div>

                {/* Plain 2-column key/value rows (Section 5.5: Zero cards in cards) */}
                <div className="space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    {t("properties.specs", "Property Specs")}
                  </span>
                  <div className="grid grid-cols-2 gap-y-2.5 text-xs">
                    <div>
                      <span className="text-[var(--ink-3)] block">{t("properties.area", "Living Area")}</span>
                      <span className="font-medium text-[var(--ink)]">{activeUnit.areaSqm == null ? UNKNOWN : `${activeUnit.areaSqm} m²`}</span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">{t("properties.monthly_rent", "Monthly Rent")}</span>
                      <span className="font-mono font-semibold text-[var(--ink)]">{euro(activeUnit.monthlyRentEur)}</span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">{t("properties.deposit", "Security Deposit")}</span>
                      <span className="font-mono text-[var(--ink-2)]">{euro(activeUnit.depositEur)}</span>
                    </div>
                    <div>
                      <span className="text-[var(--ink-3)] block">{t("properties.active_tickets", "Active Tickets")}</span>
                      <span className="font-medium text-[var(--ink)]">
                        {(activeUnit.activeTicketCount ?? 0) > 0 ? (
                          <span className="text-[var(--accent-ink)] font-semibold">
                            {activeUnit.activeTicketCount} {t("properties.open_tickets", "open")}
                          </span>
                        ) : (
                          activeUnit.activeTicketCount == null ? UNKNOWN : t("properties.no_tickets", "0 open")
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Tenant Association Section */}
                <div className="border-t border-[var(--line)] pt-4 space-y-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    {t("properties.current_tenant", "Current Leaseholder")}
                  </span>
                  {activeUnit.currentTenant ? (
                    <div className="space-y-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-[14px] text-[var(--ink)]">
                          {activeUnit.currentTenant.name}
                        </span>
                        <span className="text-[11px] text-[var(--ink-3)]">
                          {activeUnit.currentTenant.rentPaidUpToDate == null ? t("Payment Status") : activeUnit.currentTenant.rentPaidUpToDate ? `✓ ${t("Rent up to date")}` : `⚠ ${t("Overdue")}`}
                        </span>
                      </div>

                      <div className="space-y-1 text-[var(--ink-2)]">
                        <div className="flex items-center gap-2">
                          <Phone className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>{activeUnit.currentTenant.phone ?? UNKNOWN}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>{activeUnit.currentTenant.email ?? UNKNOWN}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Calendar className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>
                            {t("tenants.lease_end", "Lease ends")} {activeUnit.currentTenant.leaseEnd ?? UNKNOWN}
                          </span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-xs text-[var(--ink-3)] italic">
                      {activeUnit.status === "vacant"
                        ? t("properties.vacant_desc", "No current leaseholder. Unit is vacant and available for listing.")
                        : t("properties.occupied_not_linked", "Occupied under an active lease; the tenant is not linked yet.")}
                    </div>
                  )}
                </div>

                {/* Notes (Plain text, no box) */}
                {activeUnit.notes && (
                  <div className="border-t border-[var(--line)] pt-4 space-y-1">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                      {t("Notes")}
                    </span>
                    <p className="text-xs text-[var(--ink-2)] leading-relaxed italic">
                      {activeUnit.notes}
                    </p>
                  </div>
                )}
              </div>

              {/* Sticky Footer: Ghost actions + One primary button (Section 5.5 / 5.4) */}
              <div className="p-4 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeUnit.unitNumber)}`)}
                  disabled={!activeUnit.currentTenant}
                  title={activeUnit.currentTenant ? undefined : "Vacant: no tenant to have messages with"}
                  className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                >
                  {t("inbox.show_threads", "View messages")}
                </Button>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeUnit.unitNumber)}`)}
                  className="text-xs border border-[var(--line)] text-[var(--ink-2)]"
                >
                  {t("properties.view_tickets", "View tickets")}
                </Button>
              </div>
            </div>
          )}
        </div>

        {/* ------------------------------------------------------------- */}
        {/* MOBILE NAVIGATION STACK (< 768px): One Pane at a Time          */}
        {/* Screen 1: Complexes list                                       */}
        {/* Screen 2: Complex Screen (5 units per row grid)                */}
        {/* Screen 3: Unit Screen (Full detail + sticky footer)            */}
        {/* ------------------------------------------------------------- */}
        <div className="md:hidden flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">

          {/* SCREEN 1: Complexes List (when ?complex is not in URL) */}
          {isMobileComplexList && (
            <div className="flex-1 flex flex-col min-h-0 overflow-y-auto bg-[var(--bg)] pb-[calc(4rem+env(safe-area-inset-bottom))]">
              {/* Portfolio header */}
              <div className="p-4 border-b border-[var(--line)] bg-[var(--pane)]">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                  Portfolio Directory
                </span>
                <div className="text-[14px] text-[var(--ink)] font-semibold">
                  {portfolioStats.total} Units across {PROPERTY_COMPLEXES.length}{" "}
                  {PROPERTY_COMPLEXES.length === 1 ? "Complex" : "Complexes"}
                </div>
                <div className="text-xs text-[var(--ink-3)] mt-0.5">
                  Occupancy rate: <span className="font-semibold text-[var(--ink)]">{portfolioStats.rate}</span>
                </div>
              </div>

              {/* Complexes Row List */}
              <div className="divide-y divide-[var(--line)] bg-[var(--pane)]">
                {PROPERTY_COMPLEXES.map((comp) => (
                  <button
                    key={comp.id}
                    onClick={() => handleSelectComplex(comp.id)}
                    className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer"
                  >
                    <div className="min-w-0 flex-1 pr-3">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-[15px] text-[var(--ink)] truncate">
                          {comp.name}
                        </span>
                        <span className="font-mono text-xs font-semibold text-[var(--ink-3)] shrink-0">
                          {comp.occupiedUnits}/{comp.totalUnits}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--ink-3)] mt-0.5 truncate">
                        {comp.address}
                      </div>
                      {/* Bar indicator */}
                      <div className="w-full bg-[var(--line)] h-1 rounded-full overflow-hidden mt-2">
                        <div
                          className="bg-[var(--ink)] h-full rounded-full"
                          style={{ width: `${comp.occupancyRate}%` }}
                        />
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0 ml-2" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* SCREEN 2: Complex Screen (when ?complex=id but no &unit=id) */}
          {isMobileComplexScreen && (
            <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-[var(--bg)] pb-[calc(3.5rem+env(safe-area-inset-bottom))]">
              {/* Screen Header with Back Arrow to Complexes List */}
              <div className="h-14 px-4 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-2 shrink-0">
                <div className="flex items-center gap-2.5 min-w-0">
                  <button
                    onClick={handleMobileBack}
                    className="p-1.5 -ml-1.5 shrink-0 text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer"
                    aria-label="Back to complexes"
                  >
                    <ArrowLeft className="w-5 h-5" />
                  </button>
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-semibold text-[var(--ink)] truncate leading-tight">
                      {activeComplex.name}
                    </h2>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {activeComplex.occupiedUnits} occupied · {activeComplex.vacantUnits} vacant
                    </p>
                  </div>
                </div>

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeComplex.name)}`)}
                  className="text-xs border border-[var(--line)] shrink-0"
                >
                  Tickets
                </Button>
              </div>

              {/* Mobile Controls: 3 Tabs (scrollable) + Search input */}
              <div className="p-3 border-b border-[var(--line)] bg-[var(--pane)] space-y-2 shrink-0">
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
                    All ({activeComplex.units.length})
                  </button>
                  <button
                    onClick={() => setActiveTab("occupied")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "occupied"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Occupied ({activeComplex.units.filter((u) => u.status !== "vacant").length})
                  </button>
                  <button
                    onClick={() => setActiveTab("vacant")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors",
                      activeTab === "vacant"
                        ? "bg-[var(--ink)] text-white"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border border-[var(--line)]"
                    )}
                  >
                    Vacant ({activeComplex.units.filter((u) => u.status === "vacant").length})
                  </button>
                </div>

                <div className="relative">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--ink-3)]" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search unit or tenant..."
                    className="w-full pl-8 pr-3 py-2 text-sm bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
                  />
                </div>
              </div>

              {/* Mobile Unit Grid */}
              <div className="flex-1 p-3 overflow-y-auto">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-2 px-1">
                  Tap unit for full details
                </span>
                <div className="grid grid-cols-3 min-[420px]:grid-cols-4 gap-2.5">
                  {filteredUnits.map((unit) => {
                    const isNotice = unit.status === "notice_given";

                    return (
                      <button
                        key={unit.id}
                        onClick={() => handleSelectUnit(unit)}
                        className={cn(
                          "flex flex-col items-center justify-center p-2 rounded-lg border text-center min-h-[76px] min-w-0 transition-all cursor-pointer active:scale-95",
                          unit.status === "occupied"
                            ? "bg-[var(--pane)] border-[var(--line)] text-[var(--ink)]"
                            : isNotice
                            ? "bg-[var(--selected)] border-[var(--accent)] text-[var(--accent-ink)]"
                            : "bg-[var(--bg)] border-dashed border-[var(--line)] text-[var(--ink-3)]"
                        )}
                      >
                        <span className="font-mono text-[13px] font-bold leading-none block truncate max-w-full">
                          {unit.unitNumber}
                        </span>
                        <span
                          className={cn(
                            "w-1.5 h-1.5 rounded-full mt-1.5",
                            unit.status === "occupied"
                              ? "bg-[var(--ink)]"
                              : isNotice
                              ? "bg-[var(--accent)]"
                              : "bg-[var(--line)]"
                          )}
                        />
                        <span className="text-[10px] text-[var(--ink-3)] font-mono mt-1 tabular-nums">
                          {unit.monthlyRentEur == null ? UNKNOWN : `€${Math.round(unit.monthlyRentEur / 100) * 100 / 1000}k`}
                        </span>
                      </button>
                    );
                  })}
                </div>
                {filteredUnits.length === 0 && (
                  <div className="text-center py-12 text-[var(--ink-3)] text-xs">
                    No units match your search.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* SCREEN 3: Unit Screen (Full detail + sticky footer) */}
          {isMobileUnitScreen && activeUnit && (
            <div className="flex-1 flex flex-col bg-[var(--pane)] min-h-0 overflow-hidden pb-[calc(3.5rem+env(safe-area-inset-bottom))]">
              {/* Header with Back Arrow to Complex Screen */}
              <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between gap-2 shrink-0 bg-[var(--pane)]">
                <div className="flex items-center gap-2.5 min-w-0">
                  <button
                    onClick={handleMobileBack}
                    className="p-1.5 -ml-1.5 shrink-0 text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer"
                    aria-label="Back to complex"
                  >
                    <ArrowLeft className="w-5 h-5" />
                  </button>
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-bold text-[var(--ink)] truncate">
                      Unit {activeUnit.unitNumber}
                    </h2>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {activeUnit.complexName}
                    </p>
                  </div>
                </div>

                <div className="shrink-0">
                  <StatusText status={activeUnit.status} />
                </div>
              </div>

              {/* Scrollable Unit Profile */}
              <div className="flex-1 overflow-y-auto p-4 space-y-5">
                <div>
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                    Address
                  </span>
                  <div className="text-[14px] text-[var(--ink)] font-medium">
                    {activeUnit.fullAddress}
                  </div>
                </div>

                {/* Plain 2-column key/value grid (No cards in cards) */}
                <div className="border-t border-[var(--line)] pt-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-2">
                    Unit Details
                  </span>
                  <div className="grid grid-cols-2 gap-y-3 text-sm">
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Area</span>
                      <span className="font-medium text-[var(--ink)]">{activeUnit.areaSqm == null ? UNKNOWN : `${activeUnit.areaSqm} m²`}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Monthly Rent</span>
                      <span className="font-mono font-semibold text-[var(--ink)]">{euro(activeUnit.monthlyRentEur)}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Deposit</span>
                      <span className="font-mono text-[var(--ink-2)]">{euro(activeUnit.depositEur)}</span>
                    </div>
                    <div>
                      <span className="text-xs text-[var(--ink-3)] block">Active Tickets</span>
                      <span className="font-medium text-[var(--ink)]">
                        {(activeUnit.activeTicketCount ?? 0) > 0 ? (
                          <span className="text-[var(--accent-ink)] font-semibold">
                            {activeUnit.activeTicketCount} open
                          </span>
                        ) : (
                          activeUnit.activeTicketCount == null ? UNKNOWN : "0 open"
                        )}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Leaseholder */}
                <div className="border-t border-[var(--line)] pt-3">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-2">
                    Current Leaseholder
                  </span>
                  {activeUnit.currentTenant ? (
                    <div className="space-y-2 text-sm">
                      <div className="font-semibold text-[15px] text-[var(--ink)]">
                        {activeUnit.currentTenant.name}
                      </div>
                      <div className="space-y-1 text-xs text-[var(--ink-2)]">
                        <div className="flex items-center gap-2">
                          <Phone className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>{activeUnit.currentTenant.phone ?? UNKNOWN}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>{activeUnit.currentTenant.email ?? UNKNOWN}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Calendar className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                          <span>
                            Ends {activeUnit.currentTenant.leaseEnd ?? UNKNOWN}
                          </span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-xs text-[var(--ink-3)] italic">
                      {activeUnit.status === "vacant" ? "Vacant. No active lease." : "Occupied; the tenant is not linked yet."}
                    </div>
                  )}
                </div>

                {/* Notes */}
                {activeUnit.notes && (
                  <div className="border-t border-[var(--line)] pt-3">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                      Notes
                    </span>
                    <p className="text-xs text-[var(--ink-2)] italic leading-relaxed">
                      {activeUnit.notes}
                    </p>
                  </div>
                )}
              </div>

              {/* Sticky Footer: One screen at a time, composer or action bar at the very bottom */}
              <div className="p-3 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-2 shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/inbox?search=${encodeURIComponent(activeUnit.unitNumber)}`)}
                  className="flex-1 text-xs border border-[var(--line)] py-2.5"
                >
                  Messages
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/maintenance?search=${encodeURIComponent(activeUnit.unitNumber)}`)}
                  className="flex-1 text-xs border border-[var(--line)] py-2.5"
                >
                  Tickets
                </Button>
              </div>
            </div>
          )}

        </div>
          </div>

          {/* Ask EstateOS Side Panel (40% width on right side) */}
          <AskEstateOSPanel
            currentPageName="Properties"
            selectedContext={
              activeUnit
                ? `Unit ${activeUnit.unitNumber} (${activeComplex.name}) - ${activeUnit.fullAddress}`
                : activeComplex.name
            }
          />
        </div>
      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />


    </div>
  );
}

function PropertiesContent() {
  const [state, setState] = useState<
    { status: "loading" } | { status: "error" } | { status: "ready"; complexes: PropertyComplex[] }
  >({ status: "loading" });

  useEffect(() => {
    let isMounted = true;
    const load = () =>
      getPortfolio().then((result) => {
        if (!isMounted) return;
        if (result.ok) setState({ status: "ready", complexes: result.data });
        else setState((prev) => (prev.status === "ready" ? prev : { status: "error" }));
      });
    void load();
    const poll = setInterval(load, 30000);
    return () => {
      isMounted = false;
      clearInterval(poll);
    };
  }, []);

  if (state.status === "loading") return <PageStateShell title="Properties" message="Loading properties…" />;
  if (state.status === "error") {
    return <PageStateShell title="Properties" message="Can't reach the server. Retrying…" alert />;
  }
  if (state.complexes.length === 0) {
    return <PageStateShell title="Properties" message="No properties recorded yet." />;
  }
  return <PropertiesView complexes={state.complexes} />;
}

export default function PropertiesPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Properties...</div>}>
      <PropertiesContent />
    </Suspense>
  );
}
