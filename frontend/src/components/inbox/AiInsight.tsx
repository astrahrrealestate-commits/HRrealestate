"use client";

import React, { useState } from "react";
import { Sparkles, ChevronDown, ChevronUp, AlertTriangle, X } from "lucide-react";
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

  const defaultFacts: InsightFact[] = data.facts || [
    { label: "Ticket", value: data.ticketNumber || "#005" },
    { label: "Priority", value: data.urgency ? data.urgency.toUpperCase() : "URGENT", isAlert: true },
    { label: "Contractor", value: data.contractorName || "Chahal Bouw (Electrician)" },
    { label: "Arrival window", value: data.arrivalTime || "Today 11:30 – 12:30" },
    { label: "PO budget cap", value: "€ 650 (pre-authorized)" },
    { label: "Access", value: "Key lockbox code #4182" },
  ];

  const defaultSteps: string[] = data.whatWillHappen || [
    `Escalate incident to ticket ${data.ticketNumber || "#005"} (Emergency status)`,
    `Dispatch ${data.contractorName || "Chahal Bouw"} via WhatsApp with authorized PO cap`,
    "Send Dutch response to tenant with estimated arrival window",
    "Log autonomous work order execution to ledger audit trail",
  ];

  const summaryParts = [
    data.ticketNumber || "#005",
    data.urgency || "Urgent",
    data.contractorName || "Chahal Bouw",
    data.arrivalTime || "11:30",
  ].filter(Boolean);

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
        className="w-full px-3.5 py-2.5 flex items-center justify-between text-left text-[13px] hover:bg-[var(--selected)]/40 rounded-[var(--radius-ctl)] transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2 truncate min-w-0 pr-2">
          <Sparkles className="w-4 h-4 text-[var(--accent)] flex-shrink-0" strokeWidth={2.2} />
          <span className="font-semibold text-[var(--ink)] flex-shrink-0">
            EstateOS understood
          </span>
          <span className="text-[var(--ink-3)] truncate hidden sm:inline">
            · {summaryParts.join(" · ")}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-[var(--ink-3)] font-medium flex-shrink-0">
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
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 pt-2 text-[13px]">
            {defaultFacts.map((fact, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between py-1 border-b border-[var(--line)]/60"
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

          {/* What Will Happen - Plain Numbered List */}
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
                <Sparkles className="w-4 h-4 text-[var(--accent)]" />
                <span className="font-heading font-bold text-[16px] text-[var(--ink)]">
                  EstateOS Understood
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
          </div>
        </div>
      )}
    </div>
  );
}
