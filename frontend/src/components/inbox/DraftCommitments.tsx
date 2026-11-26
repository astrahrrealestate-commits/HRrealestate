"use client";

import React from "react";
import { ShieldAlert } from "lucide-react";

interface DraftCommitmentsProps {
  commitments?: readonly string[] | null;
}

/**
 * Lists every concrete promise or follow-up made by the selected draft right above Approve
 * so the owner sees every commitment before sending.
 */
export function DraftCommitments({ commitments }: DraftCommitmentsProps) {
  const items = (commitments ?? []).map((c) => c.trim()).filter(Boolean);
  if (items.length === 0) return null;

  return (
    <div
      data-testid="draft-commitments"
      className="px-3 py-2 border-t border-[var(--line)] bg-amber-500/5 text-[11.5px] text-[var(--ink-2)] space-y-1"
    >
      <div className="flex items-center gap-1.5 font-semibold text-[11px] uppercase tracking-wider text-[var(--ink-3)]">
        <ShieldAlert className="w-3.5 h-3.5 text-amber-600 shrink-0" />
        <span>Commitments in this reply</span>
      </div>
      <ul className="list-disc pl-5 space-y-0.5 text-[var(--ink)]">
        {items.map((item, idx) => (
          <li key={`${idx}-${item}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
