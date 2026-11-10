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
  Filter,
  Check,
  ChevronDown,
  X,
  ArrowUpRight,
  ArrowDownRight,
  AlertTriangle,
  Clock,
  CheckCircle2,
  Calendar,
  Building,
  CreditCard,
  ChevronRight,
  SlidersHorizontal,
  Download,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_TRANSACTIONS, MoneyTransaction } from "@/data/moneyMockData";
import { TransactionDetailSheet } from "@/components/money/TransactionDetailSheet";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";

type MoneyTab = "all" | "receivables" | "payables" | "overdue";

function findMatchingTransaction(
  allTx: MoneyTransaction[],
  invoiceQuery?: string | null,
  txQuery?: string | null,
  tenantQuery?: string | null
): MoneyTransaction | null {
  const q = (invoiceQuery || txQuery || tenantQuery || "").trim().toLowerCase();
  if (!q) return null;

  // 1. Exact match on reference or id
  const exact = allTx.find(
    (t) =>
      t.reference.toLowerCase() === q ||
      t.id.toLowerCase() === q ||
      t.id.replace(/^tx-/, "").toLowerCase() === q
  );
  if (exact) return exact;

  // 2. Substring / partial match on reference or counterparty or unitLabel
  const partial = allTx.find(
    (t) =>
      t.reference.toLowerCase().includes(q) ||
      t.counterparty.toLowerCase().includes(q) ||
      t.unitLabel.toLowerCase().includes(q)
  );
  if (partial) return partial;

  return null;
}

function MoneyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const superAgent = useSuperAgent();
  const { t } = useLanguage();

  const invoiceParam = searchParams?.get("invoice") || "";
  const txParam = searchParams?.get("tx") || "";
  const tenantParam = searchParams?.get("tenant") || "";

  const [activeTab, setActiveTab] = useState<MoneyTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [selectedTx, setSelectedTx] = useState<MoneyTransaction | null>(null);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);

  // Synchronize deep-link param on mount or URL change
  useEffect(() => {
    if (invoiceParam || txParam || tenantParam) {
      const matched = findMatchingTransaction(MOCK_TRANSACTIONS, invoiceParam, txParam, tenantParam);
      if (matched) {
        setSelectedTx(matched);
        if (matched.status === "overdue") {
          setActiveTab("overdue");
        } else if (matched.direction === "inflow") {
          setActiveTab("receivables");
        } else if (matched.direction === "outflow") {
          setActiveTab("payables");
        }
      }
    }
  }, [invoiceParam, txParam, tenantParam]);

  // Listen for instant custom navigation events (handles same-page Super Agent clicks)
  useEffect(() => {
    const handleCustomNav = (e: Event) => {
      const customEvent = e as CustomEvent<{ url: string }>;
      const url = customEvent?.detail?.url;
      if (url && url.includes("/money")) {
        const invMatch = url.match(/[?&]invoice=([^&]+)/);
        const txMatch = url.match(/[?&]tx=([^&]+)/);
        const tenantMatch = url.match(/[?&]tenant=([^&]+)/);
        const inv = invMatch ? decodeURIComponent(invMatch[1]) : "";
        const tx = txMatch ? decodeURIComponent(txMatch[1]) : "";
        const tnt = tenantMatch ? decodeURIComponent(tenantMatch[1]) : "";
        const matched = findMatchingTransaction(MOCK_TRANSACTIONS, inv, tx, tnt);
        if (matched) {
          setSelectedTx(matched);
          if (matched.status === "overdue") {
            setActiveTab("overdue");
          } else if (matched.direction === "inflow") {
            setActiveTab("receivables");
          } else if (matched.direction === "outflow") {
            setActiveTab("payables");
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, []);

  // Financial aggregates
  const aggregates = useMemo(() => {
    let totalInflow = 0;
    let totalOutflow = 0;
    let overdueAmount = 0;
    let overdueCount = 0;

    MOCK_TRANSACTIONS.forEach((tx) => {
      if (tx.direction === "inflow") {
        totalInflow += tx.amountEur;
        if (tx.status === "overdue") {
          overdueAmount += tx.amountEur;
          overdueCount += 1;
        }
      } else {
        totalOutflow += tx.amountEur;
      }
    });

    return {
      openRentTotal: 165734.99, // Scaled portfolio number matching Today briefing
      overdueTotal: overdueAmount,
      overdueCount,
      totalInflow,
      totalOutflow,
    };
  }, []);

  useEffect(() => {
    superAgent.setCurrentPageName("Money");
    if (selectedTx) {
      superAgent.setSelectedContext(
        `Ledger Item: ${selectedTx.reference} · ${selectedTx.counterparty} (€ ${selectedTx.amountEur}) [Status: ${selectedTx.status}, Due: ${selectedTx.dueDate}]`
      );
      superAgent.setActiveDrawerInfo({ title: selectedTx.reference, kind: "Invoice" });
    } else {
      superAgent.setSelectedContext(
        `Portfolio Ledger & Arrears (${aggregates.overdueCount} overdue tenants totaling € ${aggregates.overdueTotal.toLocaleString()})`
      );
      superAgent.setActiveDrawerInfo(null);
    }
  }, [selectedTx, aggregates, superAgent.setCurrentPageName, superAgent.setSelectedContext, superAgent.setActiveDrawerInfo]);

  // Filtered transactions
  const filteredTransactions = useMemo(() => {
    return MOCK_TRANSACTIONS.filter((tx) => {
      // Tab filter
      if (activeTab === "receivables" && tx.direction !== "inflow") return false;
      if (activeTab === "payables" && tx.direction !== "outflow") return false;
      if (activeTab === "overdue" && tx.status !== "overdue") return false;

      // Category filter (One Filter Popover / Sheet)
      if (selectedCategory !== "all" && tx.category !== selectedCategory) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesRef = tx.reference.toLowerCase().includes(q);
        const matchesParty = tx.counterparty.toLowerCase().includes(q);
        const matchesUnit = tx.unitLabel.toLowerCase().includes(q);
        const matchesDesc = tx.description.toLowerCase().includes(q);
        if (!matchesRef && !matchesParty && !matchesUnit && !matchesDesc) return false;
      }

      return true;
    });
  }, [activeTab, selectedCategory, searchQuery]);

  const handleRowClick = (tx: MoneyTransaction) => {
    setSelectedTx(tx);
    router.push(`/money?invoice=${encodeURIComponent(tx.reference)}`, { scroll: false });
  };

  const handleCloseSheet = () => {
    setSelectedTx(null);
    router.push("/money", { scroll: false });
  };

  const categories = [
    { id: "all", label: "All Categories" },
    { id: "rent", label: "Tenant Rent" },
    { id: "maintenance", label: "Contractor Repairs" },
    { id: "utilities", label: "Municipal & Utilities" },
    { id: "deposit", label: "Security Deposits" },
  ];

  return (
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar
          pageTitle="Money"
          hideSearch={true}
        />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">

        {/* Scrollable Container */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 max-w-6xl w-full mx-auto pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12">
          
          {/* Header & Inline Stats (Section 5.5: No cards inside cards, StatLine format) */}
          <div className="space-y-1">
            <h1 className="font-heading font-bold text-[24px] sm:text-[28px] text-[var(--ink)] tracking-tight">
              {t("Money & Ledger")}
            </h1>
            <p className="text-xs sm:text-[13px] text-[var(--ink-2)] font-mono">
              € 165.734,99 open rent · € {aggregates.overdueTotal.toLocaleString("nl-NL")},- overdue ({aggregates.overdueCount} tenants) · 94.5% collection rate
            </p>
          </div>

          {/* Aging Distribution Banner (Single flat pane) */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 sm:p-5 space-y-3 shadow-2xs">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                Portfolio Rent Aging Breakdown
              </span>
              <span className="font-mono text-xs text-[var(--ink)] font-semibold">
                ING Bank Automated Feed: Live
              </span>
            </div>

            {/* Segmented bar */}
            <div className="h-2 w-full rounded-full bg-[var(--selected)] overflow-hidden flex">
              <div style={{ width: "72.6%" }} className="bg-[var(--ink)] h-full" title="0–30 days: € 120.400,- (72.6%)" />
              <div style={{ width: "21.3%" }} className="bg-[var(--ink-3)] h-full" title="30–90 days: € 35.334,99 (21.3%)" />
              <div style={{ width: "6.1%" }} className="bg-[var(--accent)] h-full" title="90+ days: € 10.000,- (6.1%)" />
            </div>

            <div className="flex flex-wrap items-center justify-between text-xs text-[var(--ink-2)] pt-0.5 gap-y-1">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[var(--ink)]" />
                <span>0–30 days: € 120.400,- (72.6%)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[var(--ink-3)]" />
                <span>30–90 days: € 35.334,99 (21.3%)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
                <span className="text-[var(--accent-ink)] font-semibold">90+ days: € 10.000,- (6.1%)</span>
              </div>
            </div>
          </div>

          {/* Controls Bar: Scrollable Tabs + 1 Search Bar + 1 Filter Menu (Section 5.5 / 5.6.1) */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-3 shadow-2xs">
            
            {/* Scrollable Tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar text-xs">
              <button
                onClick={() => setActiveTab("all")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "all"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                {t("All")} ({MOCK_TRANSACTIONS.length})
              </button>
              <button
                onClick={() => setActiveTab("receivables")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "receivables"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                {t("Receivables")}
              </button>
              <button
                onClick={() => setActiveTab("payables")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "payables"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                {t("Payables")}
              </button>
              <button
                onClick={() => setActiveTab("overdue")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "overdue"
                    ? "bg-[var(--accent)] text-black font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                {t("Overdue")} ({aggregates.overdueCount})
              </button>
            </div>

            {/* Search + Single Filter Popover Button */}
            <div className="flex items-center gap-2">
              <div className="relative flex-1 sm:w-60">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search reference, tenant, unit..."
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

              {/* Single Filter Menu */}
              <div className="relative">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setIsFilterOpen(!isFilterOpen)}
                  className={cn(
                    "text-xs border border-[var(--line)] gap-1.5",
                    selectedCategory !== "all" && "bg-[var(--selected)] font-semibold border-[var(--ink-2)]"
                  )}
                >
                  <Filter className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                  <span className="hidden sm:inline">
                    {selectedCategory === "all" ? "Filter" : categories.find((c) => c.id === selectedCategory)?.label}
                  </span>
                  <ChevronDown className="w-3 h-3 text-[var(--ink-3)]" />
                </Button>

                {isFilterOpen && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setIsFilterOpen(false)} />
                    <div className="absolute right-0 top-full mt-1.5 w-52 bg-[var(--pane)] border border-[var(--line)] rounded-lg shadow-xl z-40 p-1.5 text-xs animate-in fade-in zoom-in-95 duration-100">
                      <div className="px-2.5 py-1 text-[11px] font-semibold text-[var(--ink-3)] uppercase tracking-wider">
                        Filter by Category
                      </div>
                      <div className="space-y-0.5">
                        {categories.map((cat) => (
                          <button
                            key={cat.id}
                            onClick={() => {
                              setSelectedCategory(cat.id);
                              setIsFilterOpen(false);
                            }}
                            className={cn(
                              "w-full text-left px-2.5 py-1.5 rounded-md flex items-center justify-between transition-colors cursor-pointer",
                              selectedCategory === cat.id
                                ? "bg-[var(--selected)] font-semibold text-[var(--ink)]"
                                : "hover:bg-[var(--selected)]/40 text-[var(--ink-2)]"
                            )}
                          >
                            <span>{cat.label}</span>
                            {selectedCategory === cat.id && <Check className="w-3.5 h-3.5 text-[var(--ink)]" />}
                          </button>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

          </div>

          {/* DESKTOP TABLE VIEW (>= 768px) */}
          <div className="hidden md:block bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[var(--line)] bg-[var(--selected)]/30 text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                  <th className="py-3 px-4">Ref & Item</th>
                  <th className="py-3 px-4">Counterparty / Property</th>
                  <th className="py-3 px-4">Due Date</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--line)]/60 text-xs">
                {filteredTransactions.map((tx) => {
                  const isOverdue = tx.status === "overdue";
                  const isInflow = tx.direction === "inflow";

                  return (
                    <tr
                      key={tx.id}
                      onClick={() => handleRowClick(tx)}
                      className="hover:bg-[var(--selected)]/40 transition-colors cursor-pointer h-14"
                    >
                      <td className="py-3 px-4">
                        <span className="font-mono text-[11px] text-[var(--ink-3)] block">
                          {tx.reference}
                        </span>
                        <span className="font-medium text-[var(--ink)] block truncate max-w-xs">
                          {tx.description}
                        </span>
                      </td>

                      <td className="py-3 px-4">
                        <span className="font-medium text-[var(--ink)] block">
                          {tx.counterparty}
                        </span>
                        <span className="text-[11px] text-[var(--ink-3)] block truncate max-w-xs">
                          {tx.unitLabel}
                        </span>
                      </td>

                      <td className="py-3 px-4 font-mono text-[var(--ink-2)]">
                        {tx.dueDate}
                      </td>

                      <td className="py-3 px-4">
                        {isOverdue ? (
                          <span className="text-[var(--accent-ink)] font-semibold flex items-center gap-1">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            <span>{tx.overdueDays}d overdue</span>
                          </span>
                        ) : tx.status === "paid" ? (
                          <span className="text-[var(--ink-3)]">Paid</span>
                        ) : (
                          <span className="text-[var(--ink-2)]">Pending</span>
                        )}
                      </td>

                      <td className="py-3 px-4 text-right font-mono font-semibold text-sm tabular-nums">
                        <span className={isInflow ? "text-[var(--ink)]" : "text-[var(--ink-2)]"}>
                          {isInflow ? "+" : "-"} € {tx.amountEur.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {filteredTransactions.length === 0 && (
              <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                No ledger transactions match the filter criteria.
              </div>
            )}
          </div>

          {/* MOBILE ROWS LIST (< 768px): Strictly rows instead of tables per Section 5.6.1 */}
          <div className="md:hidden divide-y divide-[var(--line)] bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs">
            {filteredTransactions.map((tx) => {
              const isOverdue = tx.status === "overdue";
              const isInflow = tx.direction === "inflow";

              return (
                <button
                  key={tx.id}
                  onClick={() => handleRowClick(tx)}
                  className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer min-h-[64px]"
                >
                  {/* Left: 2 lines per row */}
                  <div className="min-w-0 flex-1 pr-3">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-[14px] text-[var(--ink)] truncate">
                        {tx.counterparty}
                      </span>
                      <span className="font-mono font-semibold text-[14px] text-[var(--ink)] tabular-nums shrink-0">
                        {isInflow ? "+" : "-"} € {tx.amountEur.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-xs text-[var(--ink-3)] mt-0.5">
                      <span className="truncate pr-2">
                        {tx.unitLabel} · {tx.description}
                      </span>
                      {isOverdue ? (
                        <span className="text-[var(--accent-ink)] font-semibold shrink-0">
                          {tx.overdueDays}d overdue
                        </span>
                      ) : (
                        <span className="shrink-0 font-mono">{tx.dueDate}</span>
                      )}
                    </div>
                  </div>

                  <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                </button>
              );
            })}

            {filteredTransactions.length === 0 && (
              <div className="text-center py-12 text-[var(--ink-3)] text-xs">
                No ledger transactions match the filter.
              </div>
            )}
          </div>

        </main>
          </div>

          {/* Ask EstateOS Side Panel (40% width on right side) */}
          <AskEstateOSPanel
            currentPageName="Money"
            selectedContext={
              selectedTx
                ? `Ledger Item: ${selectedTx.reference} - ${selectedTx.counterparty} (€ ${selectedTx.amountEur})`
                : "Portfolio Ledger & Arrears"
            }
          />
        </div>
      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* 4. Transaction Detail in a Sheet (Section 5.6.1: Tap row for detail sheet) */}
      <TransactionDetailSheet
        transaction={selectedTx}
        onClose={handleCloseSheet}
        onAction={(actionText) => {
          router.push(`/inbox?search=${encodeURIComponent(selectedTx?.counterparty || "")}`);
        }}
      />


    </div>
  );
}

export default function MoneyPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Money...</div>}>
      <MoneyContent />
    </Suspense>
  );
}
