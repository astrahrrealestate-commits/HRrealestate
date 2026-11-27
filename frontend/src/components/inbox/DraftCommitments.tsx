"use client";

import React, { useState } from "react";
import { ChevronDown, ChevronRight, ShieldAlert, X } from "lucide-react";

interface DraftCommitmentsProps {
  commitments?: readonly string[] | null;
  defaultOpen?: boolean;
}

/**
 * Compact floating trigger pill for a draft's commitments; opens a floating review card on click
 * and closes when clicked again or dismissed.
 */
export function DraftCommitments({ commitments, defaultOpen = false }: DraftCommitmentsProps) {
  const items = (commitments ?? []).map((c) => c.trim()).filter(Boolean);
  const [open, setOpen] = useState(defaultOpen);

  if (items.length === 0) return null;

  return (
    <div data-testid="draft-commitments" className="inline-flex flex-col items-start max-w-full">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-full border border-amber-300/90 bg-amber-50/90 hover:bg-amber-100/80 px-2.5 py-1 text-[11px] font-semibold text-amber-900 shadow-2xs transition-colors cursor-pointer"
      >
        <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
        <span>Commitments ({items.length})</span>
        {open ? (
          <ChevronDown className="w-3 h-3 text-amber-700 shrink-0" />
        ) : (
          <ChevronRight className="w-3 h-3 text-amber-700 shrink-0" />
        )}
      </button>

      {open && (
        <div className="mt-1.5 w-full max-w-xl rounded-xl border border-amber-300/90 bg-amber-50/95 p-2.5 text-[11.5px] text-[var(--ink-2)] shadow-sm space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-[10.5px] uppercase tracking-wider text-amber-900/80">
              Commitments in this reply
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close commitments"
              className="p-0.5 rounded-full text-amber-800/70 hover:text-amber-950 hover:bg-amber-200/50 cursor-pointer"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
          <ul className="list-disc pl-4 space-y-0.5 text-[var(--ink)] leading-snug">
            {items.map((item, idx) => (
              <li key={`${idx}-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
