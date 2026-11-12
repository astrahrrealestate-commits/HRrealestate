"use client";

import React, { useState } from "react";
import { ChevronDown, ChevronUp, AlertTriangle, X } from "lucide-react";
import { AstraIcon } from "@/components/ui/AstraBrand";
import { cn } from "@/lib/utils";

export interface InsightFact {
  label: string;
  value: string;
  isAlert?: boolean;
}

export interface AiInsightData {
  ticketNumber?: string;
  urgency?: string;
  contractorName?: string;
  arrivalTime?: string;
  summary?: string;
  facts?: InsightFact[];
  whatWillHappen?: string[];
}

interface AiInsightProps {
  data?: AiInsightData;
  className?: string;
}

/**
 * AiInsight implements Section 5.2:
 * - One single bordered block placed after the last incoming message
 * - Collapsed to 1 clean line:
 *   "✦ EstateOS understood · #005 · Urgent · Chahal Bouw · 11:30   6 points ▾"
 * - Expanded:
 *   - Flat two-column list of rows (label, value) with no tiles and no "Checked" pills.
 *   - Only items needing a look get an orange ⚠.
 *   - "What will happen" as a plain numbered list.
 * - Mobile: opens full details in a bottom sheet.
 */
export function AiInsight({ data, className }: AiInsightProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isMobileSheetOpen, setIsMobileSheetOpen] = useState(false);

  if (!data) return null;

  const defaultFacts: InsightFact[] =
    data.facts ||
    [
      data.ticketNumber && { label: "Ticket", value: data.ticketNumber },
      data.urgency && { label: "Priority", value: data.urgency.toUpperCase(), isAlert: true },
      data.contractorName && { label: "Contractor", value: data.contractorName },
      data.arrivalTime && { label: "Arrival window", value: data.arrivalTime },
    ].filter((f): f is InsightFact => Boolean(f));

  const defaultSteps: string[] = data.whatWillHappen || [];

  const summaryParts = [data.ticketNumber, data.urgency, data.contractorName, data.arrivalTime].filter(Boolean);

  const handleToggle = () => {
    // On small screens, open bottom sheet; on desktop, expand inline
    if (typeof window !== "undefined" && window.innerWidth < 768) {
      setIsMobileSheetOpen(true);
    } else {
      setIsExpanded((prev) => !prev);
    }
  };

  return (
    <div
      className={cn(
        "border border-[var(--line)] rounded-[var(--radius-ctl)] bg-[var(--pane)] transition-all",
        className
      )}
    >
      {/* 1-Line Collapsed Summary Bar */}
      <button
        type="button"
        onClick={handleToggle}
        className="w-full px-3 sm:px-3.5 py-2 sm:py-2.5 flex items-center justify-between text-left text-[12.5px] sm:text-[13px] hover:bg-[var(--selected)]/40 rounded-[var(--radius-ctl)] transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-1.5 sm:gap-2 truncate min-w-0 pr-2">
          <AstraIcon className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-[#1a73e8] flex-shrink-0" />
          <span className="font-semibold text-[var(--ink)] flex-shrink-0">
            Astra understood
          </span>
          {data.urgency && (
            <span className="sm:hidden text-[var(--ink-3)] truncate capitalize">
              · {data.urgency}
            </span>
          )}
          <span className="text-[var(--ink-3)] truncate hidden sm:inline">
            · {summaryParts.join(" · ")}
          </span>
        </div>

        <div className="flex items-center gap-1 text-xs text-[var(--ink-3)] font-medium flex-shrink-0">
          <span>{defaultFacts.length} points</span>
          {isExpanded ? (
            <ChevronUp className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" />
          )}
        </div>
      </button>

      {/* Expanded Desktop View */}
      {isExpanded && (
        <div className="hidden md:block px-4 pb-4 pt-1 border-t border-[var(--line)] space-y-4 animate-in fade-in duration-100">
          {/* Key / Value Flat Two-Column List */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 pt-2 text-[13px]">
            {defaultFacts.map((fact, idx) => {
              const isWide = fact.label === "Intent" || (fact.value?.length ?? 0) > 28;
              return (
                <div
                  key={idx}
                  className={cn(
                    "flex items-start justify-between gap-3 py-1.5 border-b border-[var(--line)]/60 min-w-0",
                    isWide && "sm:col-span-2"
                  )}
                >
                  <span className="text-[var(--ink-3)] shrink-0">{fact.label}</span>
                  <span className="font-medium text-[var(--ink)] flex items-start justify-end gap-1.5 text-right break-words min-w-0">
                    {fact.isAlert && (
                      <AlertTriangle className="w-3.5 h-3.5 text-[var(--accent-ink)] shrink-0 mt-0.5" />
                    )}
                    <span className={cn("break-words", fact.isAlert && "text-[var(--accent-ink)] font-semibold")}>
                      {fact.value}
                    </span>
                  </span>
                </div>
              );
            })}
          </div>

          {/* What Will Happen - Plain Numbered List */}
          {defaultSteps.length > 0 && (
          <div className="pt-1">
            <span className="text-xs font-semibold text-[var(--ink-2)] uppercase tracking-wider block mb-2">
              What will happen on approval
            </span>
            <ol className="space-y-1.5 text-[13px] text-[var(--ink-2)]">
              {defaultSteps.map((step, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="font-mono text-xs text-[var(--ink-3)] w-4 flex-shrink-0 pt-0.5">
                    {idx + 1}.
                  </span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </div>
          )}
        </div>
      )}

      {/* Mobile Bottom Sheet (Section 5.6.1) */}
      {isMobileSheetOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex flex-col justify-end">
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
            onClick={() => setIsMobileSheetOpen(false)}
          />
          <div className="relative w-full bg-[var(--pane)] border-t border-[var(--line)] rounded-t-[18px] p-5 max-h-[85dvh] overflow-y-auto space-y-4 shadow-xl animate-in slide-in-from-bottom duration-200">
            <div className="flex items-center justify-between pb-3 border-b border-[var(--line)]">
              <div className="flex items-center gap-2">
                <AstraIcon className="w-4 h-4 text-[#1a73e8]" />
                <span className="font-heading font-bold text-[16px] text-[var(--ink)]">
                  Astra Understood
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIsMobileSheetOpen(false)}
                className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-2 text-[13.5px]">
              {defaultFacts.map((fact, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between py-1.5 border-b border-[var(--line)]/60"
                >
                  <span className="text-[var(--ink-3)]">{fact.label}</span>
                  <span className="font-medium text-[var(--ink)] flex items-center gap-1.5">
                    {fact.isAlert && (
                      <AlertTriangle className="w-3.5 h-3.5 text-[var(--accent-ink)]" />
                    )}
                    <span className={fact.isAlert ? "text-[var(--accent-ink)] font-semibold" : ""}>
                      {fact.value}
                    </span>
                  </span>
                </div>
              ))}
            </div>

            {defaultSteps.length > 0 && (
            <div className="pt-2">
              <span className="text-xs font-semibold text-[var(--ink-2)] uppercase tracking-wider block mb-2">
                What will happen on approval
              </span>
              <ol className="space-y-2 text-[13px] text-[var(--ink-2)]">
                {defaultSteps.map((step, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="font-mono text-xs text-[var(--ink-3)] w-4 flex-shrink-0 pt-0.5">
                      {idx + 1}.
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
            </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
