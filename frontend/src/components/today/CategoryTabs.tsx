"use client";

import React from "react";
import { cn } from "@/lib/utils";
import type { CategorySummaryItem } from "@/lib/api";
import { tabDisplay, type BusinessCategory } from "@/lib/categories";

interface CategoryTabsProps {
  summaries: readonly CategorySummaryItem[];
  activeCategory: BusinessCategory;
  onSelect: (category: BusinessCategory) => void;
}

export function CategoryTabs({ summaries, activeCategory, onSelect }: CategoryTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Business categories"
      className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pb-1"
    >
      {summaries.map((summary) => {
        const isActive = summary.category === activeCategory;
        const { label, count, hasUrgent } = tabDisplay(summary);
        return (
          <button
            key={summary.category}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-category={summary.category}
            onClick={() => onSelect(summary.category)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors whitespace-nowrap shrink-0 border cursor-pointer",
              isActive
                ? "bg-[var(--ink)] text-white border-[var(--ink)] font-semibold shadow-2xs"
                : "bg-[var(--bg)]/70 text-[var(--ink-2)] border-[var(--line)] hover:text-[var(--ink)] hover:bg-[var(--pane)]"
            )}
          >
            <span>{label}</span>
            {count !== null && (
              <span
                className={cn(
                  "tabular-nums text-[11px] font-semibold",
                  isActive ? "text-white/85" : "text-[var(--ink-3)]"
                )}
              >
                {count}
              </span>
            )}
            {hasUrgent && (
              <span
                aria-label="urgent"
                className={cn(
                  "w-1.5 h-1.5 rounded-full",
                  isActive ? "bg-amber-300" : "bg-[var(--accent)]"
                )}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
