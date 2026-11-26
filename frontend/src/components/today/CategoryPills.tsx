"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { CategoryBucket, DASHBOARD_CATEGORIES, DashboardCategoryId, DashboardTabId } from "@/lib/dashboardCategories";

interface CategoryPillsProps {
  activeTab: DashboardTabId;
  allCount: number;
  allUrgentCount: number;
  buckets: Record<DashboardCategoryId, CategoryBucket>;
  onSelect: (tab: DashboardTabId) => void;
}

/**
 * Lightweight "All" + 6-category pill tabs.
 * Scrolls horizontally on mobile (<768px) without wrapping into stacked rows.
 */
export function CategoryPills({
  activeTab,
  allCount,
  allUrgentCount,
  buckets,
  onSelect,
}: CategoryPillsProps) {
  const isAllActive = activeTab === "all";

  return (
    <nav
      aria-label="Dashboard categories"
      className="-mx-3.5 px-3.5 sm:mx-0 sm:px-0 flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5 select-none"
    >
      <button
        type="button"
        onClick={() => onSelect("all")}
        aria-pressed={isAllActive}
        className={cn(
          "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] transition-colors cursor-pointer whitespace-nowrap shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ink)]",
          isAllActive
            ? "bg-[var(--ink)] text-white font-semibold"
            : "bg-[var(--bg)] text-[var(--ink-2)] hover:bg-[var(--selected)] hover:text-[var(--ink)] font-medium"
        )}
      >
        <span>All</span>
        {allCount > 0 && (
          <span
            className={cn(
              "text-[11px] font-mono tabular-nums px-1.5 py-0.2 rounded-full leading-tight",
              isAllActive
                ? "bg-white/20 text-white font-semibold"
                : "bg-white text-[var(--ink-2)] border border-[var(--line)]"
            )}
          >
            {allCount}
          </span>
        )}
        {allUrgentCount > 0 && (
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full shrink-0",
              isAllActive ? "bg-amber-300" : "bg-[#E14D12]"
            )}
            aria-label={`${allUrgentCount} urgent`}
          />
        )}
      </button>

      {DASHBOARD_CATEGORIES.map((meta) => {
        const bucket = buckets[meta.id];
        const isActive = activeTab === meta.id;
        const hasUrgent = bucket.urgentCount > 0;
        const hasOpen = bucket.openCount > 0;

        return (
          <button
            key={meta.id}
            type="button"
            onClick={() => onSelect(meta.id)}
            aria-pressed={isActive}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] transition-colors cursor-pointer whitespace-nowrap shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ink)]",
              isActive
                ? "bg-[var(--ink)] text-white font-semibold"
                : "bg-[var(--bg)] text-[var(--ink-2)] hover:bg-[var(--selected)] hover:text-[var(--ink)] font-medium"
            )}
          >
            <span>{meta.label}</span>
            {hasOpen && (
              <span
                className={cn(
                  "text-[11px] font-mono tabular-nums px-1.5 py-0.2 rounded-full leading-tight",
                  isActive
                    ? "bg-white/20 text-white font-semibold"
                    : "bg-white text-[var(--ink-2)] border border-[var(--line)]"
                )}
              >
                {bucket.openCount}
              </span>
            )}
            {hasUrgent && (
              <span
                className={cn(
                  "w-1.5 h-1.5 rounded-full shrink-0",
                  isActive ? "bg-amber-300" : "bg-[#E14D12]"
                )}
                aria-label={`${bucket.urgentCount} urgent`}
              />
            )}
          </button>
        );
      })}
    </nav>
  );
}
