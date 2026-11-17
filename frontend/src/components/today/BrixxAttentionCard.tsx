"use client";

import React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/Card";
import type { AttentionItem } from "@/lib/api";

const KIND_LABEL: Record<AttentionItem["kind"], string> = {
  ticket: "Maintenance",
  rent: "Rent",
  lease: "Lease",
};

function age(item: AttentionItem): string {
  if (item.kind === "lease") return `in ${item.ageDays} days`;
  return item.kind === "rent" ? `${item.ageDays} days late` : `open ${item.ageDays} days`;
}

/** What BRIXX holds for the owner: open tickets, rent in arrears, leases ending. Hidden when there is none. */
export function BrixxAttentionCard({
  items,
  total,
  urgentTotal,
  onlyUrgent,
}: {
  items: AttentionItem[];
  total: number;
  urgentTotal: number;
  onlyUrgent: boolean;
}) {
  const shown = onlyUrgent ? items.filter((i) => i.urgent && i.kind !== "rent") : items;
  if (shown.length === 0) return null;
  return (
    <Card className="mb-4" data-testid="brixx-attention">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">From BRIXX</h3>
        <span className="text-xs text-[var(--ink-2)]">
          {onlyUrgent ? urgentTotal : total} item{(onlyUrgent ? urgentTotal : total) === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="divide-y divide-[var(--line)]">
        {shown.map((item) => {
          const isRent = item.kind === "rent";
          const isUrgent = item.urgent && !isRent;
          return (
            <li key={item.id} className="py-2 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded",
                      isUrgent
                        ? "bg-amber-100 text-amber-900"
                        : isRent
                          ? "bg-amber-50 text-amber-800 border border-amber-200/60"
                          : "bg-[var(--pane)] text-[var(--ink-2)]"
                    )}
                  >
                    {isUrgent ? "Urgent" : isRent ? "Unreconciled" : KIND_LABEL[item.kind]}
                  </span>
                  <span className="text-sm font-medium truncate">
                    {isRent ? item.title.replace("rent overdue", "rent billed") : item.title}
                  </span>
                </div>
                <p className="text-xs text-[var(--ink-2)] truncate">
                  {[item.unitLabel, item.partyName, item.detail, isRent ? "Settlement in Exact Online" : null]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <div className="shrink-0 flex flex-col items-end gap-1">
                <span className="text-xs text-[var(--ink-2)]">{age(item)}</span>
                <Link href={item.href} className="text-xs text-[var(--accent)] hover:underline">
                  Open
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
