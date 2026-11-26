"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, MessageSquareText } from "lucide-react";
import {
  getCategoryDesk,
  getDashboardCategories,
  type CategoryDeskData,
  type CategoryNextAction,
  type CategorySummaryItem,
} from "@/lib/api";
import { categoryLabel, fallbackCategorySummaries, pickInitialCategory, type BusinessCategory } from "@/lib/categories";
import { CategoryTabs } from "@/components/today/CategoryTabs";
import { cn } from "@/lib/utils";

interface CategoryDeskViewProps {
  summaries: readonly CategorySummaryItem[];
  activeCategory: BusinessCategory;
  desk: CategoryDeskData | null;
  loading?: boolean;
  offline?: boolean;
  onSelectCategory: (category: BusinessCategory) => void;
  onAskAstra?: (action: CategoryNextAction) => void;
}

export function CategoryDeskView({
  summaries,
  activeCategory,
  desk,
  loading = false,
  offline = false,
  onSelectCategory,
  onAskAstra,
}: CategoryDeskViewProps) {
  const label = categoryLabel(activeCategory) ?? activeCategory;
  const actions = desk?.actions ?? [];

  return (
    <section
      aria-label="Category desk"
      className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 sm:p-5 space-y-3"
    >
      <CategoryTabs summaries={summaries} activeCategory={activeCategory} onSelect={onSelectCategory} />

      <div className="flex items-center justify-between gap-2 pt-0.5">
        <p className="text-[13px] text-[var(--ink-2)]">
          <span className="font-semibold text-[var(--ink)]">{label}</span>
          {offline ? (
            <span> — Offline. Connect to load open actions.</span>
          ) : desk?.brief ? (
            <span> — &ldquo;{desk.brief}&rdquo;</span>
          ) : loading ? (
            <span> — Loading actions…</span>
          ) : (
            <span> — Quiet. Nothing waiting right now.</span>
          )}
        </p>
        {loading && <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--ink-3)] shrink-0" />}
      </div>

      {!offline && actions.length > 0 && (
        <ol className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
          {actions.map((action, index) => {
            const isDraftReady = action.kind === "approve_draft" || action.approval_id !== null;
            return (
              <li
                key={action.id}
                className="py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
              >
                <div className="flex items-start gap-2.5 min-w-0">
                  <span className="w-5 text-right font-mono text-xs text-[var(--ink-3)] tabular-nums shrink-0 pt-0.5">
                    {index + 1}
                  </span>
                  <div className="min-w-0 space-y-0.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span
                        className={cn(
                          "text-[13px] font-semibold text-[var(--ink)]",
                          (action.urgency === "emergency" || action.urgency === "high") && "text-[var(--accent-ink)]"
                        )}
                      >
                        {action.title}
                      </span>
                      {action.why && (
                        <span className="text-[12px] text-[var(--ink-2)]">— {action.why}</span>
                      )}
                    </div>
                    {action.prepared && (
                      <p className="text-[12px] text-[var(--ink-3)] line-clamp-2">{action.prepared}</p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0 pl-7 sm:pl-0">
                  <Link
                    href={action.target_url || "/inbox"}
                    className="inline-flex items-center px-2.5 py-1 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--bg)] hover:bg-[var(--selected)] text-[12px] font-semibold text-[var(--ink)] transition-colors whitespace-nowrap"
                  >
                    {isDraftReady ? "Review draft" : "Open"}
                  </Link>
                  {onAskAstra && (
                    <button
                      type="button"
                      onClick={() => onAskAstra(action)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[12px] font-medium text-[var(--ink-2)] hover:text-[var(--ink)] transition-colors cursor-pointer whitespace-nowrap"
                    >
                      <MessageSquareText className="w-3 h-3" />
                      <span>Ask Astra</span>
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

interface CategoryDeskProps {
  onAskAstra?: (action: CategoryNextAction) => void;
}

export function CategoryDesk({ onAskAstra }: CategoryDeskProps) {
  const [summaries, setSummaries] = useState<CategorySummaryItem[]>(() => fallbackCategorySummaries());
  const [activeCategory, setActiveCategory] = useState<BusinessCategory>("maintenance");
  const [desk, setDesk] = useState<CategoryDeskData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [offline, setOffline] = useState<boolean>(false);

  useEffect(() => {
    let active = true;
    getDashboardCategories().then((loaded) => {
      if (!active) return;
      if (!loaded) {
        setOffline(true);
        setLoading(false);
        return;
      }
      setOffline(false);
      setSummaries(loaded);
      const initial = pickInitialCategory(loaded);
      setActiveCategory(initial);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (offline) return;
    let active = true;
    getCategoryDesk(activeCategory).then((data) => {
      if (!active) return;
      if (!data) {
        setOffline(true);
      } else {
        setDesk(data);
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [activeCategory, offline]);

  const handleSelect = (category: BusinessCategory) => {
    setLoading(true);
    setActiveCategory(category);
  };

  return (
    <CategoryDeskView
      summaries={summaries}
      activeCategory={activeCategory}
      desk={desk}
      loading={loading}
      offline={offline}
      onSelectCategory={handleSelect}
      onAskAstra={onAskAstra}
    />
  );
}
