"use client";

import React, { useEffect } from "react";
import { X, ArrowUpRight, ArrowDownRight, CheckCircle2, AlertTriangle, Clock, Building, Calendar, CreditCard, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MoneyTransaction } from "@/data/moneyMockData";
import { useSuperAgent } from "@/context/SuperAgentContext";

interface TransactionDetailSheetProps {
  transaction: MoneyTransaction | null;
  onClose: () => void;
  onAction?: (actionText: string) => void;
}

/**
 * Bottom Sheet on mobile / Slide-over sheet on desktop
 * Adheres to Section 5.5 and 5.6.1:
 * "detail in a sheet, plain key/value rows without cards"
 */
export function TransactionDetailSheet({
  transaction,
  onClose,
  onAction,
}: TransactionDetailSheetProps) {
  const superAgent = useSuperAgent();

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (transaction) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [transaction, onClose]);

  if (!transaction) return null;

  const isOverdue = transaction.status === "overdue";
  const isInflow = transaction.direction === "inflow";

  return (
    <div className="fixed inset-0 z-50 flex items-end md:items-center md:justify-end bg-black/50 md:bg-black/20 backdrop-blur-xs md:backdrop-blur-none">
      
      {/* Backdrop click dismiss */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Sheet panel: Full-width bottom sheet on mobile, 440px right panel on desktop */}
      <div className="relative w-full md:w-[440px] md:h-full max-h-[85vh] md:max-h-full bg-[var(--pane)] border-t md:border-t-0 md:border-l border-[var(--line)] rounded-t-2xl md:rounded-none flex flex-col shadow-2xl overflow-hidden animate-in slide-in-from-bottom md:slide-in-from-right duration-200">
        
        {/* Mobile handle indicator */}
        <div className="w-12 h-1.5 bg-[var(--line)] rounded-full mx-auto mt-2.5 mb-1 md:hidden" />

        {/* Header */}
        <div className="h-14 px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
          <div className="min-w-0 pr-2">
            <span className="text-[11px] font-mono text-[var(--ink-3)] block truncate">
              {transaction.reference} · {transaction.category.toUpperCase()}
            </span>
            <h3 className="text-[15px] font-bold text-[var(--ink)] truncate">
              {transaction.counterparty}
            </h3>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* 1-Click Fast Toggle to Super Agent (Unified Right Rail) */}
            <button
              type="button"
              onClick={() => superAgent.setIsOpen(true)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11.5px] font-semibold text-emerald-400 bg-[#161A1D] hover:bg-[#1E2328] border border-[#252B32] rounded-lg transition-colors cursor-pointer"
              title="Ask Super Agent about this invoice"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Ask Agent</span>
            </button>

            <button
              onClick={onClose}
              className="p-1.5 text-[var(--ink-3)] hover:text-[var(--ink)] rounded-md hover:bg-[var(--selected)] transition-colors cursor-pointer"
              aria-label="Close detail sheet"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Sheet Content (Scrollable) */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-6 text-xs text-[var(--ink)]">
          
          {/* Amount Display */}
          <div className="bg-[var(--selected)]/40 border border-[var(--line)] rounded-xl p-4 flex items-center justify-between">
            <div>
              <span className="text-[11px] text-[var(--ink-3)] block">
                {isInflow ? "Receivable Amount" : "Payable Amount"}
              </span>
              <div className="text-[24px] font-mono font-bold text-[var(--ink)] tracking-tight mt-0.5">
                {isInflow ? "+" : "-"} € {transaction.amountEur.toLocaleString("nl-NL", { minimumFractionDigits: 2 })}
              </div>
            </div>

            <div>
              {isOverdue ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold bg-[var(--accent)]/15 text-[var(--accent-ink)] border border-[var(--accent)]/30">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>{transaction.overdueDays}d Overdue</span>
                </span>
              ) : transaction.status === "paid" ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium text-emerald-600 bg-emerald-500/10 border border-emerald-500/20">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Settled</span>
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium text-[var(--ink-2)] bg-[var(--selected)] border border-[var(--line)]">
                  <Clock className="w-3.5 h-3.5" />
                  <span>Pending</span>
                </span>
              )}
            </div>
          </div>

          {/* Description */}
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
              Transaction Purpose
            </span>
            <p className="text-[14px] font-medium text-[var(--ink)]">
              {transaction.description}
            </p>
          </div>

          {/* Key / Value Details (Plain rows, zero cards in cards) */}
          <div className="border-t border-[var(--line)] pt-4 space-y-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
              Ledger Specifications
            </span>
            <div className="grid grid-cols-2 gap-y-3 text-xs">
              <div>
                <span className="text-[var(--ink-3)] block">Target Property</span>
                <span className="font-medium text-[var(--ink)]">{transaction.unitLabel}</span>
              </div>
              <div>
                <span className="text-[var(--ink-3)] block">Settlement Channel</span>
                <span className="font-medium text-[var(--ink)]">{transaction.paymentMethod}</span>
              </div>
              <div>
                <span className="text-[var(--ink-3)] block">Due Date</span>
                <span className="font-mono font-medium text-[var(--ink)]">{transaction.dueDate}</span>
              </div>
              <div>
                <span className="text-[var(--ink-3)] block">Settlement Date</span>
                <span className="font-mono text-[var(--ink-2)]">{transaction.paidDate || "Unsettled"}</span>
              </div>
            </div>
          </div>

          {/* AI Autonomous Suggestion (Section 5.5: Orange accent reserved for AI) */}
          {transaction.aiSuggestedAction && (
            <div className="border-t border-[var(--line)] pt-4 space-y-1.5">
              <span className="text-xs font-semibold text-[var(--accent-ink)] flex items-center gap-1">
                <span>✦ EstateOS Recommended Action</span>
              </span>
              <p className="text-xs text-[var(--ink-2)] italic leading-relaxed bg-[var(--selected)]/30 p-3 rounded-lg border border-[var(--line)]">
                {transaction.aiSuggestedAction}
              </p>
            </div>
          )}

          {/* Notes */}
          {transaction.notes && (
            <div className="border-t border-[var(--line)] pt-4 space-y-1">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block">
                Audit Trail Notes
              </span>
              <p className="text-xs text-[var(--ink-2)] leading-relaxed">
                {transaction.notes}
              </p>
            </div>
          )}

        </div>

        {/* Sticky Footer */}
        <div className="p-4 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-3 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-xs border border-[var(--line)]"
          >
            Close
          </Button>

          {isOverdue ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                if (onAction) onAction(transaction.aiSuggestedAction || "Send formal reminder");
                onClose();
              }}
              className="text-xs bg-[var(--accent)] hover:bg-[var(--accent)]/90 text-black font-semibold"
            >
              ✦ Send payment nudge
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                alert(`Downloaded bank statement for ${transaction.reference}`);
                onClose();
              }}
              className="text-xs border border-[var(--line)]"
            >
              Export receipt
            </Button>
          )}
        </div>

      </div>
    </div>
  );
}
