"use client";

import React, { useState, useMemo, useEffect, useCallback, Suspense } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import {
  FileSpreadsheet,
  Copy,
  Check,
  ChevronDown,
  Search,
  RefreshCw,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";
import { toCsv } from "@/lib/csv";
import { formatClock } from "@/lib/clock";
import { isReportId, loadReports, type ReportsLoad } from "@/lib/reportsApi";
import { PageStateShell } from "@/components/portfolio/PageStateShell";
import type { ReportKind } from "@/types/reports";
import { ReportPickerSheet } from "@/components/reports/ReportPickerSheet";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";

function ReportsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, isLoading: authLoading } = useAuth();
  const role = user?.role ?? "";

  const [loaded, setLoaded] = useState<ReportsLoad | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isPickerSheetOpen, setIsPickerSheetOpen] = useState(false);
  const [isDesktopPickerOpen, setIsDesktopPickerOpen] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [searchQuery, setSearchQuery] = useState("");

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const next = await loadReports();
    if (next.sessionExpired) {
      router.replace("/login");
      return;
    }
    setLoaded(next);
    setRefreshing(false);
  }, [router]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch of the live reports
    void refresh();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  // Esc closes the desktop report dropdown
  useEffect(() => {
    if (!isDesktopPickerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsDesktopPickerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isDesktopPickerOpen]);

  const reports = useMemo(() => loaded?.reports ?? [], [loaded]);
  const allowed = useMemo(() => reports.filter((r) => r.roles.includes(role)), [reports, role]);

  // The selected report lives in the URL (?report=arrears) so a refresh or a shared link opens the same one.
  const requestedId = searchParams.get("report");
  const requested = isReportId(requestedId) ? reports.find((r) => r.id === requestedId) : undefined;
  const denied = requested !== undefined && !requested.roles.includes(role);
  const activeReport = denied ? undefined : (requested ?? allowed[0]);
  const selectedReportId: ReportKind | undefined = activeReport?.id;

  const selectReport = (id: ReportKind) => {
    setSearchQuery("");
    router.replace(`${pathname}?report=${id}`, { scroll: false });
  };

  const filteredRows = useMemo(() => {
    if (!activeReport) return [];
    if (!searchQuery.trim()) return activeReport.rows;
    const q = searchQuery.toLowerCase();
    return activeReport.rows.filter((row) => Object.values(row).some((val) => String(val).toLowerCase().includes(q)));
  }, [activeReport, searchQuery]);

  const handleCopyAsCsv = async () => {
    if (!activeReport) return;
    try {
      await navigator.clipboard.writeText(toCsv(activeReport.columns, filteredRows));
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    setTimeout(() => setCopyState("idle"), 2500);
  };

  if (!loaded || authLoading) return <PageStateShell title="Reports" message="Loading reports…" />;

  return (
    <div className="h-dvh bg-[#1B1B1B] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#1B1B1B]">
        <TopCommandBar
          pageTitle="Reports"
          hideSearch={true}
        />

        {/* WORKSPACE ROW with 40% Super Agent */}
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">

        {/* Scrollable Container */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 max-w-7xl w-full mx-auto pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12">

          {/* Header Bar with Title, Description, and "Copy as CSV" (Section 5.6.1: Copy as CSV stays in the header) */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--line)] pb-5">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-heading font-bold text-[24px] sm:text-[28px] text-[var(--ink)] tracking-tight">
                  {activeReport?.name ?? "Reports"}
                </h1>
              </div>
              <p className="text-xs sm:text-[13px] text-[var(--ink-2)] mt-1 max-w-2xl leading-relaxed">
                {activeReport?.description ?? ""}
              </p>
            </div>

            {/* Action: Copy as CSV stays in the header per Section 5.6.1 */}
            <div className="flex items-center gap-2.5 shrink-0">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCopyAsCsv}
                disabled={!activeReport || activeReport.failed}
                className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] gap-1.5 shadow-2xs"
              >
                {copyState === "copied" ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span>Copied CSV</span>
                  </>
                ) : copyState === "failed" ? (
                  <>
                    <AlertTriangle className="w-3.5 h-3.5 text-red-600" />
                    <span role="alert">Copy failed: allow clipboard access</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                    <span>Copy as CSV</span>
                  </>
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void refresh()}
                disabled={refreshing}
                aria-label="Refresh reports"
                className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] gap-1.5 shadow-2xs"
              >
                <RefreshCw className={cn("w-3.5 h-3.5 text-[var(--ink-3)]", refreshing && "animate-spin")} />
                <span>Refresh</span>
              </Button>
            </div>
          </div>

          {/* Controls Bar: Report Selector Trigger + Search */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-3 shadow-2xs">

            {/* Report Picker Button: Sheet on Mobile (< 768px), Dropdown on Desktop (>= 768px) */}
            <div className="relative">
              {/* Mobile trigger opens ReportPickerSheet */}
              <button
                onClick={() => setIsPickerSheetOpen(true)}
                className="md:hidden flex items-center justify-between gap-2 px-3.5 py-2 rounded-md bg-[var(--bg)] border border-[var(--line)] text-xs font-semibold text-[var(--ink)] w-full text-left"
              >
                <div className="flex items-center gap-2 truncate">
                  <FileSpreadsheet className="w-4 h-4 text-[var(--ink-2)] shrink-0" />
                  <span className="truncate">{activeReport?.name ?? "Select report"}</span>
                </div>
                <ChevronDown className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" />
              </button>

              {/* Desktop trigger */}
              <button
                onClick={() => setIsDesktopPickerOpen(!isDesktopPickerOpen)}
                aria-haspopup="listbox"
                aria-expanded={isDesktopPickerOpen}
                className="hidden md:flex items-center justify-between gap-2.5 px-3.5 py-1.5 rounded-md bg-[var(--bg)] border border-[var(--line)] text-xs font-semibold text-[var(--ink)] hover:bg-[var(--selected)]/40 transition-colors cursor-pointer"
              >
                <FileSpreadsheet className="w-3.5 h-3.5 text-[var(--ink-2)]" />
                <span>{activeReport?.name ?? "Select report"}</span>
                <ChevronDown className="w-3.5 h-3.5 text-[var(--ink-3)] ml-1" />
              </button>

              {/* Desktop Dropdown Popover */}
              {isDesktopPickerOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setIsDesktopPickerOpen(false)} />
                  <div className="absolute left-0 top-full mt-1.5 w-72 bg-[var(--pane)] border border-[var(--line)] rounded-lg shadow-xl z-40 p-1.5 text-xs animate-in fade-in zoom-in-95 duration-100">
                    <div className="px-2.5 py-1 text-[11px] font-semibold text-[var(--ink-3)] uppercase tracking-wider">
                      Portfolio Reports
                    </div>
                    <div className="space-y-0.5">
                      {allowed.map((rep) => (
                        <button
                          key={rep.id}
                          onClick={() => {
                            selectReport(rep.id);
                            setIsDesktopPickerOpen(false);
                          }}
                          className={cn(
                            "w-full text-left px-2.5 py-2 rounded-md flex items-center justify-between transition-colors cursor-pointer",
                            selectedReportId === rep.id
                              ? "bg-[var(--selected)] font-semibold text-[var(--ink)]"
                              : "hover:bg-[var(--selected)]/40 text-[var(--ink-2)]"
                          )}
                        >
                          <div className="min-w-0 pr-2">
                            <span className="block truncate font-medium text-[var(--ink)]">{rep.name}</span>
                            <span className="block text-[10px] text-[var(--ink-3)]">{rep.period}</span>
                          </div>
                          {selectedReportId === rep.id && <Check className="w-3.5 h-3.5 text-[var(--ink)] shrink-0" />}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Search Input */}
            <div className="relative sm:w-64">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter table rows..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink-2)]"
              />
            </div>

          </div>

          {!activeReport ? (
            <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] py-16 text-center text-xs text-[var(--ink-2)]" role="alert">
              {denied
                ? "Your role does not have access to this report. Pick one from the list."
                : "No reports are available for your role."}
            </div>
          ) : activeReport.failed ? (
            <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] py-16 text-center text-xs text-[var(--ink-2)]" role="alert">
              Could not load this report. Check the connection and press Refresh.
            </div>
          ) : (
          <>
          {/* TABLE CONTAINER (Section 5.6.1: Table scrolls inside its own container with a sticky first column) */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] shadow-2xs overflow-hidden">
            <div className="overflow-x-auto relative w-full">
              <table className="w-full text-left border-collapse min-w-[680px]">
                <thead>
                  <tr className="border-b border-[var(--line)] bg-[var(--selected)]/30 text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                    {activeReport.columns.map((column, idx) => (
                      <th
                        key={column}
                        className={cn(
                          "py-3.5 px-4 whitespace-nowrap",
                          // Sticky First Column (Section 5.6.1)
                          idx === 0 &&
                            "sticky left-0 z-20 bg-[var(--pane)] shadow-[2px_0_4px_-2px_rgba(0,0,0,0.1)] border-r border-[var(--line)]/60"
                        )}
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--line)]/60 text-xs">
                  {filteredRows.map((row, rIdx) => (
                    <tr
                      key={rIdx}
                      className="hover:bg-[var(--selected)]/40 transition-colors h-13"
                    >
                      {activeReport.columns.map((column, cIdx) => {
                        const cellVal = row[column] ?? "";
                        const isFirst = cIdx === 0;

                        return (
                          <td
                            key={column}
                            title={String(cellVal)}
                            className={cn(
                              "py-3.5 px-4 whitespace-nowrap text-[var(--ink)] max-w-[22rem] truncate",
                              isFirst &&
                                "sticky left-0 z-10 bg-[var(--pane)] font-semibold shadow-[2px_0_4px_-2px_rgba(0,0,0,0.1)] border-r border-[var(--line)]/60 text-[var(--ink)]"
                            )}
                          >
                            {cellVal}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {filteredRows.length === 0 && (
              <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                {activeReport.rows.length === 0 ? activeReport.emptyMessage : "No report rows match your filter."}
              </div>
            )}
          </div>

          {/* Table summary footer */}
          <div className="flex items-center justify-between text-xs text-[var(--ink-3)] px-1">
            <span>Showing {filteredRows.length} of {activeReport.rows.length} rows</span>
            <span className="font-mono">{activeReport.period} · Live data, loaded {formatClock(loaded.loadedAt)}</span>
          </div>
          </>
          )}

        </main>
          </div>

          {/* Ask EstateOS Side Panel (40% width on right side) */}
          <AskEstateOSPanel
            currentPageName="Reports"
            selectedContext={activeReport ? `Report: ${activeReport.name} (${activeReport.period})` : "Reports"}
          />
        </div>
      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* 4. Report Picker Bottom Sheet on Mobile (Section 5.6.1) */}
      <ReportPickerSheet
        isOpen={isPickerSheetOpen}
        onClose={() => setIsPickerSheetOpen(false)}
        reports={allowed}
        selectedReportId={selectedReportId}
        onSelectReport={(rep) => selectReport(rep.id)}
      />


    </div>
  );
}

export default function ReportsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Reports...</div>}>
      <ReportsContent />
    </Suspense>
  );
}
