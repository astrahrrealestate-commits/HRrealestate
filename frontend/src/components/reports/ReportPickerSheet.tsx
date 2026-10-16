"use client";

import React, { useEffect } from "react";
import { X, Check, BarChart3, FileSpreadsheet, ArrowRight, ShieldCheck, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_REPORTS, ReportTemplate } from "@/data/reportsMockData";

interface ReportPickerSheetProps {
  isOpen: boolean;
  onClose: () => void;
  selectedReportId: string;
  onSelectReport: (report: ReportTemplate) => void;
}

/**
 * Mobile Report Picker as a Bottom Sheet
 * Adheres to Section 5.6.1:
 * "Report picker as a sheet on mobile"
 */
export function ReportPickerSheet({
  isOpen,
  onClose,
  selectedReportId,
  onSelectReport,
}: ReportPickerSheetProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end bg-black/60 backdrop-blur-xs md:hidden animate-in fade-in duration-150">
      
      {/* Backdrop */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Bottom Sheet panel */}
      <div className="relative w-full max-h-[85vh] bg-[var(--pane)] border-t border-[var(--line)] rounded-t-2xl flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-bottom duration-200">
        
        {/* Handle bar */}
        <div className="w-12 h-1.5 bg-[var(--line)] rounded-full mx-auto mt-2.5 mb-1" />

        {/* Header */}
        <div className="h-13 px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-[var(--ink-2)]" />
            <span className="text-sm font-bold text-[var(--ink)]">
              Select Portfolio Report
            </span>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-[var(--ink-3)] hover:text-[var(--ink)] rounded-md cursor-pointer"
            aria-label="Close report picker"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* List of Report Options */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2 pb-[calc(2rem+env(safe-area-inset-bottom))]">
          {MOCK_REPORTS.map((report) => {
            const isSelected = report.id === selectedReportId;

            return (
              <button
                key={report.id}
                onClick={() => {
                  onSelectReport(report);
                  onClose();
                }}
                className={cn(
                  "w-full text-left p-3.5 rounded-xl border transition-all flex flex-col gap-1 cursor-pointer select-none",
                  isSelected
                    ? "bg-[var(--selected)] border-[var(--ink)] shadow-2xs"
                    : "bg-[var(--pane)] border-[var(--line)] hover:border-[var(--ink-3)]"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[14px] font-semibold text-[var(--ink)] truncate">
                    {report.name}
                  </span>
                  {isSelected && <Check className="w-4 h-4 text-[var(--ink)] shrink-0 ml-2" />}
                </div>

                <p className="text-xs text-[var(--ink-3)] leading-relaxed">
                  {report.description}
                </p>

                <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--ink-2)] pt-1">
                  <span>Period: {report.period}</span>
                  <span>·</span>
                  <span>{report.rows.length} records</span>
                </div>
              </button>
            );
          })}
        </div>

      </div>
    </div>
  );
}
