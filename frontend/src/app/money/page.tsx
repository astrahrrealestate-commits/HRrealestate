"use client";

import React, { useState, useMemo, useEffect, Suspense, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import {
  Search,
  Check,
  ChevronDown,
  X,
  AlertTriangle,
  Clock,
  Calendar,
  Building,
  ChevronRight,
  Download,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_TRANSACTIONS, MoneyTransaction } from "@/data/moneyMockData";
import { TransactionDetailSheet } from "@/components/money/TransactionDetailSheet";
import { RentAnalyticsLineChart } from "@/components/money/RentAnalyticsLineChart";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import {
  getRentLedger,
  getRentAnalytics,
  RentLedgerItem,
  RentAnalyticsResponse,
  HistoricalTrendPoint,
} from "@/lib/api";

type TenantRentTab = "all" | "paid" | "overdue" | "pending";
type ChartViewMode = "revenue" | "occupancy";

function formatMonthLabel(monthStr: string): string {
  try {
    const [year, m] = monthStr.split("-").map(Number);
    const date = new Date(year, m - 1, 1);
    return date.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  } catch {
    return monthStr;
  }
}

function ledgerItemToTransaction(item: RentLedgerItem): MoneyTransaction {
  return {
    id: item.id,
    reference: item.invoiceNumber,
    type: "rent_receivable",
    category: "rent",
    description: `Monthly Rent — ${formatMonthLabel(item.billingMonth)}`,
    counterparty: item.tenantName,
    unitLabel: item.unitLabel,
    amountEur: item.contractRentEur,
    direction: "inflow",
    dueDate: item.dueDate,
    paidDate: item.paidAt || undefined,
    status: item.status === "paid" ? "paid" : item.status === "overdue" ? "overdue" : "pending",
    overdueDays: item.overdueDays,
    paymentMethod: item.paymentMethod as any,
    notes: item.notes || undefined,
    aiSuggestedAction: item.aiSuggestedAction || undefined,
    tenantPhone: item.tenantPhone || undefined,
    tenantEmail: item.tenantEmail || undefined,
    unitAddress: item.unitAddress || undefined,
  };
}

function findMatchingTransaction(
  allTx: MoneyTransaction[],
  invoiceQuery?: string | null,
  txQuery?: string | null,
  tenantQuery?: string | null
): MoneyTransaction | null {
  const q = (invoiceQuery || txQuery || tenantQuery || "").trim().toLowerCase();
  if (!q) return null;

  const exact = allTx.find(
    (t) =>
      t.reference.toLowerCase() === q ||
      t.id.toLowerCase() === q ||
      t.id.replace(/^tx-/, "").toLowerCase() === q
  );
  if (exact) return exact;

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

  // Ledger & Analytics State
  const [selectedMonth, setSelectedMonth] = useState<string>("2026-11");
  const [availableMonths, setAvailableMonths] = useState<string[]>([
    "2026-11",
    "2026-10",
    "2026-09",
  ]);
  const [isMonthDropdownOpen, setIsMonthDropdownOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TenantRentTab>("all");
  const [chartView, setChartView] = useState<ChartViewMode>("revenue");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTx, setSelectedTx] = useState<MoneyTransaction | null>(null);

  // Live Data State
  const [ledgerItems, setLedgerItems] = useState<RentLedgerItem[]>([]);
  const [analytics, setAnalytics] = useState<RentAnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Fetch Rent Analytics (6-month trend & MoM summary)
  const fetchAnalytics = useCallback(async () => {
    try {
      const data = await getRentAnalytics();
      if (data) {
        setAnalytics(data);
      }
    } catch (err) {
      console.warn("Failed to load rent analytics:", err);
    }
  }, []);

  // Fetch Rent Ledger items for selected month
  const fetchLedger = useCallback(async (month: string) => {
    setIsLoading(true);
    try {
      const res = await getRentLedger({ month });
      if (res) {
        setLedgerItems(res.items);
        if (res.availableMonths && res.availableMonths.length > 0) {
          setAvailableMonths(res.availableMonths);
        }
      }
    } catch (err) {
      console.warn("Failed to load rent ledger:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAnalytics();
  }, [fetchAnalytics]);

  useEffect(() => {
    fetchLedger(selectedMonth);
  }, [selectedMonth, fetchLedger]);

  // Map ledger items to standard MoneyTransaction models
  const allTransactions = useMemo<MoneyTransaction[]>(() => {
    if (ledgerItems.length > 0) {
      return ledgerItems.map(ledgerItemToTransaction);
    }
    return MOCK_TRANSACTIONS.filter((t) => t.category === "rent" || t.type === "rent_receivable");
  }, [ledgerItems]);

  // Financial aggregates calculated from live items
  const aggregates = useMemo(() => {
    let totalScheduled = 0;
    let totalCollected = 0;
    let overdueAmount = 0;
    let overdueCount = 0;
    let paidCount = 0;
    let pendingCount = 0;

    allTransactions.forEach((tx) => {
      totalScheduled += tx.amountEur;
      if (tx.status === "paid") {
        totalCollected += tx.amountEur;
        paidCount += 1;
      } else if (tx.status === "overdue") {
        overdueAmount += tx.amountEur;
        overdueCount += 1;
      } else {
        pendingCount += 1;
      }
    });

    const portfolioScheduled = analytics?.currentMonth?.totalScheduled || 165734.0;
    const portfolioCollected = analytics?.currentMonth?.totalCollected || (portfolioScheduled - overdueAmount);
    const collectionRate = analytics?.currentMonth?.collectionRate || (totalScheduled > 0 ? (totalCollected / totalScheduled) * 100 : 98.0);
    const occupiedUnits = analytics?.currentMonth?.occupiedUnits ?? 110;
    const totalUnits = analytics?.currentMonth?.totalUnits ?? 110;
    const occupancyRate = analytics?.currentMonth?.occupancyRate ?? 100.0;

    return {
      totalScheduled: portfolioScheduled,
      totalCollected: portfolioCollected,
      overdueTotal: overdueAmount,
      overdueCount,
      paidCount,
      pendingCount,
      collectionRate,
      occupiedUnits,
      totalUnits,
      occupancyRate,
      momChangePct: analytics?.previousMonth?.momChangePct ?? -1.95,
      previousMonthCollected: analytics?.previousMonth?.totalCollected ?? 165734.0,
      previousRate: analytics?.previousMonth?.collectionRate ?? 100.0,
      previousOccupancyRate: analytics?.previousMonth?.occupancyRate ?? 100.0,
    };
  }, [allTransactions, analytics]);

  // Synchronize deep-link param on mount or URL change
  useEffect(() => {
    if (invoiceParam || txParam || tenantParam) {
      const matched = findMatchingTransaction(allTransactions, invoiceParam, txParam, tenantParam);
      if (matched) {
        setSelectedTx(matched);
        if (matched.status === "overdue") {
          setActiveTab("overdue");
        } else if (matched.status === "paid") {
          setActiveTab("paid");
        }
      }
    }
  }, [invoiceParam, txParam, tenantParam, allTransactions]);

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
        const matched = findMatchingTransaction(allTransactions, inv, tx, tnt);
        if (matched) {
          setSelectedTx(matched);
          if (matched.status === "overdue") {
            setActiveTab("overdue");
          } else if (matched.status === "paid") {
            setActiveTab("paid");
          }
        }
      }
    };
    window.addEventListener("estateos:navigate", handleCustomNav);
    return () => window.removeEventListener("estateos:navigate", handleCustomNav);
  }, [allTransactions]);

  useEffect(() => {
    superAgent.setCurrentPageName("Money");
    if (selectedTx) {
      superAgent.setSelectedContext(
        `Tenant Rent Item: ${selectedTx.reference} · ${selectedTx.counterparty} (€ ${selectedTx.amountEur}) [Status: ${selectedTx.status}, Due: ${selectedTx.dueDate}]`
      );
      superAgent.setActiveDrawerInfo({ title: selectedTx.reference, kind: "Invoice" });
    } else {
      superAgent.setSelectedContext(
        `Tenant Rent & Collections Ledger (${aggregates.overdueCount} overdue tenants totaling € ${aggregates.overdueTotal.toLocaleString("nl-NL")})`
      );
      superAgent.setActiveDrawerInfo(null);
    }
  }, [selectedTx, aggregates, superAgent]);

  // Filtered transactions for the tenant view
  const filteredTransactions = useMemo(() => {
    return allTransactions.filter((tx) => {
      if (activeTab === "paid" && tx.status !== "paid") return false;
      if (activeTab === "overdue" && tx.status !== "overdue") return false;
      if (activeTab === "pending" && tx.status !== "pending") return false;

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
  }, [allTransactions, activeTab, searchQuery]);

  const handleRowClick = (tx: MoneyTransaction) => {
    setSelectedTx(tx);
    router.push(`/money?invoice=${encodeURIComponent(tx.reference)}`, { scroll: false });
  };

  const handleCloseSheet = () => {
    setSelectedTx(null);
    router.push("/money", { scroll: false });
  };

  const handleExportCSV = () => {
    const headers = "Invoice Number,Tenant Name,Unit,Contract Rent EUR,Status,Due Date,Settlement Date,Overdue Days,Payment Method\n";
    const rows = filteredTransactions
      .map(
        (t) =>
          `"${t.reference}","${t.counterparty}","${t.unitLabel}",${t.amountEur},"${t.status}","${t.dueDate}","${t.paidDate || ""}",${t.overdueDays || 0},"${t.paymentMethod}"`
      )
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `Tenant_Rent_Roll_${selectedMonth}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Historical trend points (with revenue + occupancy)
  const trendPoints: HistoricalTrendPoint[] = useMemo(() => {
    if (analytics?.historicalTrend && analytics.historicalTrend.length > 0) {
      return analytics.historicalTrend;
    }
    return [
      { month: "Jun", billingMonth: "2026-06", scheduled: 162000, collected: 162000, overdue: 0, rate: 100, occupiedUnits: 104, totalUnits: 110, occupancyRate: 94.5 },
      { month: "Jul", billingMonth: "2026-07", scheduled: 163500, collected: 163500, overdue: 0, rate: 100, occupiedUnits: 106, totalUnits: 110, occupancyRate: 96.4 },
      { month: "Aug", billingMonth: "2026-08", scheduled: 164000, collected: 164000, overdue: 0, rate: 100, occupiedUnits: 107, totalUnits: 110, occupancyRate: 97.3 },
      { month: "Sep", billingMonth: "2026-09", scheduled: 165000, collected: 163150, overdue: 1850, rate: 98.8, occupiedUnits: 108, totalUnits: 110, occupancyRate: 98.2 },
      { month: "Oct", billingMonth: "2026-10", scheduled: 165734, collected: 165734, overdue: 0, rate: 100, occupiedUnits: 110, totalUnits: 110, occupancyRate: 100.0 },
      { month: "Nov", billingMonth: "2026-11", scheduled: 165734, collected: 162494, overdue: 3240, rate: 98.0, occupiedUnits: 110, totalUnits: 110, occupancyRate: 100.0 },
    ];
  }, [analytics]);

  const maxTrendScheduled = useMemo(() => {
    return Math.max(...trendPoints.map((p) => p.scheduled), 170000);
  }, [trendPoints]);

  return (
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar pageTitle="Money" hideSearch={true} />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">

            {/* Scrollable Container */}
            <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 max-w-6xl w-full mx-auto pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12">
              
              {/* Header with Title and Month Dropdown */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h1 className="font-heading font-semibold text-[22px] sm:text-[24px] text-[var(--ink)] tracking-tight">
                      {t("Tenant Rent & Collections Ledger")}
                    </h1>
                    <span className="px-2 py-0.5 rounded text-[11px] font-mono text-[var(--ink-2)] border border-[var(--line)] bg-[var(--selected)]/40">
                      Live Mirror
                    </span>
                  </div>
                  <p className="text-xs text-[var(--ink-2)]">
                    Real-time lease collection tracking, settled receipts, and tenant arrears management.
                  </p>
                </div>

                {/* Top Action Bar: Month Selector & Export */}
                <div className="flex items-center gap-2">
                  {/* Month Selector Dropdown */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setIsMonthDropdownOpen(!isMonthDropdownOpen)}
                      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)]/40 text-xs font-medium text-[var(--ink)] transition-colors cursor-pointer shadow-2xs"
                    >
                      <Calendar className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                      <span>{formatMonthLabel(selectedMonth)}</span>
                      <ChevronDown className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                    </button>

                    {isMonthDropdownOpen && (
                      <>
                        <div
                          className="fixed inset-0 z-30"
                          onClick={() => setIsMonthDropdownOpen(false)}
                        />
                        <div className="absolute right-0 top-full mt-1.5 w-48 bg-[var(--pane)] border border-[var(--line)] rounded-lg shadow-xl z-40 p-1.5 text-xs animate-in fade-in zoom-in-95 duration-100">
                          <div className="px-2.5 py-1 text-[10px] font-semibold text-[var(--ink-3)] uppercase tracking-wider">
                            Billing Cycle
                          </div>
                          <div className="space-y-0.5">
                            {availableMonths.map((m) => (
                              <button
                                key={m}
                                type="button"
                                onClick={() => {
                                  setSelectedMonth(m);
                                  setIsMonthDropdownOpen(false);
                                }}
                                className={cn(
                                  "w-full text-left px-2.5 py-1.5 rounded-md flex items-center justify-between transition-colors cursor-pointer",
                                  selectedMonth === m
                                    ? "bg-[var(--selected)] font-semibold text-[var(--ink)]"
                                    : "hover:bg-[var(--selected)]/40 text-[var(--ink-2)]"
                                )}
                              >
                                <span>{formatMonthLabel(m)}</span>
                                {selectedMonth === m && (
                                  <Check className="w-3.5 h-3.5 text-[var(--ink)]" />
                                )}
                              </button>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Export CSV Button */}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleExportCSV}
                    className="text-xs border border-[var(--line)] gap-1.5"
                    title="Export Rent Roll to CSV"
                  >
                    <Download className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                    <span className="hidden sm:inline">Export CSV</span>
                  </Button>
                </div>
              </div>

              {/* KPI StatLine Cards: Quiet, monochrome, high-trust typography */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
                {/* 1. Scheduled Rent */}
                <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 shadow-2xs space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Scheduled Rent ({trendPoints.find((p) => p.billingMonth === selectedMonth)?.month || "Nov"})
                  </span>
                  <div className="text-xl sm:text-2xl font-mono font-semibold text-[var(--ink)] tracking-tight tabular-nums">
                    € {aggregates.totalScheduled.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                  </div>
                  <span className="text-[11px] text-[var(--ink-3)] block font-mono">
                    {aggregates.totalUnits} portfolio units
                  </span>
                </div>

                {/* 2. Collected Rent */}
                <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 shadow-2xs space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Collected Rent
                  </span>
                  <div className="text-xl sm:text-2xl font-mono font-semibold text-[var(--ink)] tracking-tight tabular-nums">
                    € {aggregates.totalCollected.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                  </div>
                  <span className="text-[11px] text-[var(--ink-2)] block font-mono">
                    {aggregates.collectionRate.toFixed(1)}% collected on time
                  </span>
                </div>

                {/* 3. Overdue Arrears */}
                <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 shadow-2xs space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Overdue Arrears
                  </span>
                  <div className="text-xl sm:text-2xl font-mono font-semibold text-[var(--ink)] tracking-tight tabular-nums">
                    € {aggregates.overdueTotal.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                  </div>
                  <span className="text-[11px] text-[var(--ink-2)] block font-mono">
                    {aggregates.overdueCount} {aggregates.overdueCount === 1 ? "tenant" : "tenants"} in arrears
                  </span>
                </div>

                {/* 4. Occupancy / MoM Growth */}
                <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 shadow-2xs space-y-1">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                    Portfolio Occupancy
                  </span>
                  <div className="text-xl sm:text-2xl font-mono font-semibold text-[var(--ink)] tracking-tight flex items-center gap-1.5 tabular-nums">
                    <span>{aggregates.occupancyRate.toFixed(1)}%</span>
                  </div>
                  <span className="text-[11px] text-[var(--ink-3)] block font-mono">
                    {aggregates.occupiedUnits} / {aggregates.totalUnits} leased units
                  </span>
                </div>
              </div>

              {/* Dual Visual Trends: Monthly Revenue Trend OR Portfolio Occupancy Trend */}
              <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-5 sm:p-6 shadow-2xs space-y-4">
                
                {/* Chart Header + View Switcher */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-[14px] font-semibold text-[var(--ink)] tracking-tight">
                      {chartView === "revenue"
                        ? "Monthly Rent Revenue & Collection Trend (Last 6 Months)"
                        : "Portfolio Occupancy Progression (Last 6 Months)"}
                    </h3>
                    <p className="text-xs text-[var(--ink-3)]">
                      {chartView === "revenue"
                        ? "Comparing scheduled lease commitments against collected receipts. Click a bar to filter ledger."
                        : "Tracking occupied residential units over time (growing from 94.5% to 100.0%)."}
                    </p>
                  </div>

                  {/* Switcher Toggle (Revenue vs Occupancy) */}
                  <div className="inline-flex items-center p-0.5 bg-[var(--selected)]/60 rounded-md border border-[var(--line)] self-start sm:self-auto text-xs">
                    <button
                      type="button"
                      onClick={() => setChartView("revenue")}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors cursor-pointer",
                        chartView === "revenue"
                          ? "bg-[var(--ink)] text-white shadow-xs"
                          : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                      )}
                    >
                      <BarChart3 className="w-3.5 h-3.5" />
                      <span>Revenue</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setChartView("occupancy")}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors cursor-pointer",
                        chartView === "occupancy"
                          ? "bg-[var(--ink)] text-white shadow-xs"
                          : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                      )}
                    >
                      <Users className="w-3.5 h-3.5" />
                      <span>Occupancy</span>
                    </button>
                  </div>
                </div>

                {/* Chart Legend (Apex Line Chart - Monochrome & Understated) */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-mono text-[var(--ink-2)] border-b border-[var(--line)] pb-3">
                  <div className="flex items-center gap-4">
                    {chartView === "revenue" ? (
                      <>
                        <div className="flex items-center gap-2">
                          <span className="w-4 h-0.5 border-t border-dashed border-[#94A3B8]" />
                          <span>Scheduled Target</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="w-4 h-0.5 bg-[#0A1B2F]" />
                          <span className="font-semibold text-[var(--ink)]">Settled Rent</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="flex items-center gap-2">
                          <span className="w-4 h-0.5 bg-[#0A1B2F]" />
                          <span className="font-semibold text-[var(--ink)]">Portfolio Occupancy Rate (%)</span>
                        </div>
                      </>
                    )}
                  </div>

                  <span className="text-[11px] text-[var(--ink-3)] hidden sm:inline">
                    Click node to select cycle
                  </span>
                </div>

                {/* Apex Line Graph */}
                <div className="w-full pt-1">
                  <RentAnalyticsLineChart
                    trendPoints={trendPoints}
                    selectedMonth={selectedMonth}
                    onSelectMonth={setSelectedMonth}
                    chartView={chartView}
                  />
                </div>
              </div>

              {/* Controls Bar: Tenant Tabs + Search Input */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-3 shadow-2xs">
                
                {/* Strict Tenant Tabs (Monochrome styling) */}
                <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar text-xs">
                  <button
                    type="button"
                    onClick={() => setActiveTab("all")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                      activeTab === "all"
                        ? "bg-[var(--ink)] text-white font-semibold"
                        : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                    )}
                  >
                    {t("All Tenants")} ({allTransactions.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("paid")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                      activeTab === "paid"
                        ? "bg-[var(--ink)] text-white font-semibold"
                        : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                    )}
                  >
                    {t("Settled / Paid")} ({aggregates.paidCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("overdue")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                      activeTab === "overdue"
                        ? "bg-[var(--ink)] text-white font-semibold"
                        : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                    )}
                  >
                    {t("Overdue Arrears")} ({aggregates.overdueCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("pending")}
                    className={cn(
                      "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                      activeTab === "pending"
                        ? "bg-[var(--ink)] text-white font-semibold"
                        : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                    )}
                  >
                    {t("Pending")} ({aggregates.pendingCount})
                  </button>
                </div>

                {/* Search Bar */}
                <div className="flex items-center gap-2">
                  <div className="relative flex-1 sm:w-64">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search tenant, unit, invoice..."
                      className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery("")}
                        className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ink-3)] hover:text-[var(--ink)]"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

              </div>

              {/* DESKTOP TABLE VIEW (>= 768px): Quiet, restrained monochrome palette */}
              <div className="hidden md:block bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--line)] bg-[var(--selected)]/20 text-[11px] font-mono uppercase tracking-wider text-[var(--ink-3)]">
                      <th className="py-3 px-4">Status</th>
                      <th className="py-3 px-4">Invoice Reference</th>
                      <th className="py-3 px-4">Tenant & Unit</th>
                      <th className="py-3 px-4">Contract Rent</th>
                      <th className="py-3 px-4">Settlement / Due Date</th>
                      <th className="py-3 px-4 text-right">Payment Channel</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--line)]/60 text-xs">
                    {filteredTransactions.map((tx) => {
                      const isOverdue = tx.status === "overdue";

                      return (
                        <tr
                          key={tx.id}
                          onClick={() => handleRowClick(tx)}
                          className="hover:bg-[var(--selected)]/30 transition-colors cursor-pointer h-14"
                        >
                          {/* Status Tag (Quiet, monochrome) */}
                          <td className="py-3 px-4">
                            {isOverdue ? (
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-medium text-[var(--ink)] bg-[var(--selected)] border border-[var(--line)]">
                                <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink)]" />
                                <span>{tx.overdueDays}d overdue</span>
                              </span>
                            ) : tx.status === "paid" ? (
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-medium text-[var(--ink-2)] bg-[var(--selected)]/40 border border-[var(--line)]">
                                <Check className="w-3 h-3 text-[var(--ink-2)]" />
                                <span>PAID</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono text-[var(--ink-3)] bg-[var(--selected)]/20 border border-[var(--line)]">
                                <Clock className="w-3 h-3" />
                                <span>Pending</span>
                              </span>
                            )}
                          </td>

                          {/* Invoice Reference */}
                          <td className="py-3 px-4">
                            <span className="font-mono text-[12px] font-medium text-[var(--ink)] block">
                              {tx.reference}
                            </span>
                            <span className="text-[11px] text-[var(--ink-3)] block truncate max-w-xs">
                              {tx.description}
                            </span>
                          </td>

                          {/* Tenant & Unit */}
                          <td className="py-3 px-4">
                            <span className="font-medium text-[13px] text-[var(--ink)] block">
                              {tx.counterparty}
                            </span>
                            <span className="text-[11px] text-[var(--ink-3)] block truncate max-w-xs">
                              {tx.unitLabel}
                            </span>
                          </td>

                          {/* Contract Rent Amount */}
                          <td className="py-3 px-4 font-mono font-semibold text-[14px] text-[var(--ink)] tabular-nums">
                            € {tx.amountEur.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                          </td>

                          {/* Settlement / Due Date */}
                          <td className="py-3 px-4">
                            {tx.paidDate ? (
                              <div>
                                <span className="font-mono text-[var(--ink)] font-medium block">
                                  {tx.paidDate}
                                </span>
                                <span className="text-[10px] text-[var(--ink-3)] block font-mono">
                                  Due {tx.dueDate}
                                </span>
                              </div>
                            ) : (
                              <div>
                                <span className="font-mono text-[var(--ink)] font-medium block">
                                  Due {tx.dueDate}
                                </span>
                                <span className="text-[10px] text-[var(--ink-3)] block font-mono">
                                  {tx.overdueDays} days in arrears
                                </span>
                              </div>
                            )}
                          </td>

                          {/* Settlement Channel */}
                          <td className="py-3 px-4 text-right text-[11px] font-mono text-[var(--ink-2)]">
                            {tx.paymentMethod}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>

                {filteredTransactions.length === 0 && (
                  <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                    {isLoading ? "Loading tenant rent ledger..." : "No tenant rent records match the filter criteria."}
                  </div>
                )}
              </div>

              {/* MOBILE ROWS LIST (< 768px) */}
              <div className="md:hidden divide-y divide-[var(--line)] bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs">
                {filteredTransactions.map((tx) => {
                  const isOverdue = tx.status === "overdue";

                  return (
                    <button
                      key={tx.id}
                      type="button"
                      onClick={() => handleRowClick(tx)}
                      className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer min-h-[64px]"
                    >
                      <div className="min-w-0 flex-1 pr-3">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-[14px] text-[var(--ink)] truncate">
                            {tx.counterparty}
                          </span>
                          <span className="font-mono font-semibold text-[14px] text-[var(--ink)] tabular-nums shrink-0">
                            € {tx.amountEur.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
                          </span>
                        </div>

                        <div className="flex items-center justify-between text-xs text-[var(--ink-3)] mt-0.5">
                          <span className="truncate pr-2">
                            {tx.unitLabel} · {tx.reference}
                          </span>
                          {isOverdue ? (
                            <span className="text-[var(--ink)] font-mono shrink-0">
                              {tx.overdueDays}d overdue
                            </span>
                          ) : tx.paidDate ? (
                            <span className="text-[var(--ink-2)] font-mono shrink-0">
                              {tx.paidDate}
                            </span>
                          ) : (
                            <span className="shrink-0 font-mono">Due {tx.dueDate}</span>
                          )}
                        </div>
                      </div>

                      <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                    </button>
                  );
                })}

                {filteredTransactions.length === 0 && (
                  <div className="text-center py-12 text-[var(--ink-3)] text-xs">
                    {isLoading ? "Loading..." : "No tenant rent records found."}
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
                ? `Tenant Rent Item: ${selectedTx.reference} - ${selectedTx.counterparty} (€ ${selectedTx.amountEur})`
                : "Tenant Rent & Collections Ledger"
            }
          />
        </div>
      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* 4. Transaction Detail in a Sheet */}
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
