"use client";

import React, { useState, useRef, useEffect } from "react";
import { Search, ChevronDown, RotateCw, X, SlidersHorizontal, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLanguage } from "@/context/LanguageContext";

export interface FilterTab {
  id: string;
  label: string;
  count?: number;
}

export interface FilterOption {
  id: string;
  label: string;
  count?: number;
}

export interface FilterGroup {
  id: string;
  title: string;
  options: FilterOption[];
}

export interface SortChoice {
  id: string;
  label: string;
}

export interface FilterBarProps {
  tabs: FilterTab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  filterGroups?: FilterGroup[];
  selectedFilterIds?: string[];
  onFilterToggle?: (filterId: string) => void;
  onClearFilters?: () => void;
  sortOptions?: SortChoice[];
  sortBy?: string;
  onSortChange?: (sortId: string) => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  refreshTooltip?: string;
  searchPlaceholder?: string;
  headerStrip?: React.ReactNode;
  leadingControl?: React.ReactNode;
  trailingControl?: React.ReactNode;
  className?: string;
}

/**
 * Container-adaptive FilterBar using Tailwind v4 `@container` queries.
 * Reflows cleanly whether placed inside a 260px split column or a 1200px full-width list.
 */
export function FilterBar({
  tabs,
  activeTab,
  onTabChange,
  searchQuery,
  onSearchChange,
  filterGroups = [],
  selectedFilterIds = [],
  onFilterToggle,
  onClearFilters,
  sortOptions,
  sortBy,
  onSortChange,
  onRefresh,
  isRefreshing = false,
  refreshTooltip = "Sync mailbox",
  searchPlaceholder = "Search...",
  headerStrip,
  leadingControl,
  trailingControl,
  className,
}: FilterBarProps) {
  const { t } = useLanguage();
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const [isSortOpen, setIsSortOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const sortRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (popoverRef.current && !popoverRef.current.contains(target)) {
        setIsPopoverOpen(false);
      }
      if (sortRef.current && !sortRef.current.contains(target)) {
        setIsSortOpen(false);
      }
    }
    if (isPopoverOpen || isSortOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isPopoverOpen, isSortOpen]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA"].includes((event.target as HTMLElement)?.tagName)
      ) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const visibleGroups = filterGroups
    .map((group) => ({
      ...group,
      options:
        group.id === "type"
          ? group.options
          : group.options.filter((opt) => opt.count === undefined || opt.count > 0),
    }))
    .filter((group) => group.options.length > 0);

  const activeFilterCount = selectedFilterIds.length;
  const currentSortLabel = sortOptions?.find((s) => s.id === sortBy)?.label;

  return (
    <div className={cn("@container/filter flex flex-col gap-1.5 w-full relative z-20", className)}>
      <div className="flex flex-col gap-1.5 p-2 @[420px]/filter:p-2.5 bg-[var(--pane)] border-b border-[var(--line)] min-w-0">
        {headerStrip && (
          <div className="flex items-center justify-between gap-2 min-w-0 pb-1 border-b border-[var(--line)]/60">
            {headerStrip}
          </div>
        )}

        {/* Row 1: View Tabs (wrap cleanly on narrow sidebars so nothing clips like "Sno...") */}
        <div className="flex items-center justify-between gap-2 min-w-0">
          <div className="flex flex-wrap items-center gap-1 flex-1 min-w-0 bg-[var(--bg)] p-1 rounded-[var(--radius-ctl)] border border-[var(--line)]">
            {leadingControl && <div className="shrink-0 pl-0.5">{leadingControl}</div>}
            {tabs.map((tab) => {
              const isActive = tab.id === activeTab;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => onTabChange(tab.id)}
                  className={cn(
                    "shrink-0 inline-flex items-center justify-center gap-1 px-2 py-0.5 rounded-[5px] text-[11.5px] transition-all cursor-pointer select-none whitespace-nowrap",
                    isActive
                      ? "bg-[#0A1B2F] text-white font-semibold shadow-sm"
                      : "text-[var(--ink-2)] font-medium hover:text-[var(--ink)] hover:bg-black/5"
                  )}
                >
                  <span>{t(tab.label)}</span>
                  {tab.count !== undefined && (
                    <span
                      className={cn(
                        "text-[10.5px] px-1.5 py-0.2 rounded-full tabular-nums shrink-0",
                        isActive
                          ? tab.id === "needs_you" || tab.id === "needs_action"
                            ? "bg-[var(--accent)] text-[#0A0A0A] font-bold"
                            : "bg-white/20 text-white font-semibold"
                          : tab.id === "needs_you" || tab.id === "needs_action"
                            ? "bg-[var(--accent)] text-[#0A0A0A] font-bold"
                            : "bg-[var(--line)] text-[var(--ink-2)]"
                      )}
                    >
                      {tab.count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {trailingControl && (
            <div className="hidden @[560px]/filter:flex items-center gap-1.5 shrink-0">
              {trailingControl}
            </div>
          )}
        </div>

        {/* Row 2: Search + Filter popover + Sort + Optional Refresh + Narrow trailing controls */}
        <div className="flex items-center gap-1.5 w-full min-w-0">
          {/* Search box */}
          <div className="relative flex-1 min-w-0">
            <Search className="w-3.5 h-3.5 text-[var(--ink-3)] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={t(searchPlaceholder)}
              className="w-full h-8 pl-8 pr-6 text-[12.5px] @[420px]/filter:text-[13px] bg-[var(--bg)] border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)] transition-colors"
            />
            {searchQuery ? (
              <button
                type="button"
                onClick={() => onSearchChange("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--ink-3)] hover:text-[var(--ink)] p-0.5 cursor-pointer"
                title={t("Clear search", "Zoekopdracht wissen")}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : (
              <kbd className="hidden @[400px]/filter:inline-block absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[var(--ink-3)] border border-[var(--line)] bg-[var(--pane)] px-1 rounded">
                /
              </kbd>
            )}
          </div>

          {/* Sort Popover Button */}
          {sortOptions && sortOptions.length > 0 && onSortChange && (
            <div className="relative shrink-0" ref={sortRef}>
              <button
                type="button"
                onClick={() => setIsSortOpen((prev) => !prev)}
                title={currentSortLabel ? `Sort: ${currentSortLabel}` : "Sort"}
                className="inline-flex items-center gap-1 h-8 px-2 @[380px]/filter:px-2.5 text-[12px] rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] text-[var(--ink-2)] hover:bg-[var(--selected)] transition-colors cursor-pointer select-none shrink-0"
              >
                <ArrowUpDown className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" />
                <span className="hidden @[440px]/filter:inline whitespace-nowrap">
                  {currentSortLabel || "Sort"}
                </span>
              </button>
              {isSortOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-40 p-1 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-ctl)] shadow-lg z-50 text-[12.5px]">
                  {sortOptions.map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        onSortChange(opt.id);
                        setIsSortOpen(false);
                      }}
                      className={cn(
                        "w-full text-left px-2.5 py-1.5 rounded-[6px] transition-colors cursor-pointer",
                        sortBy === opt.id
                          ? "bg-[var(--selected)] font-semibold text-[var(--ink)]"
                          : "text-[var(--ink-2)] hover:bg-[var(--selected)]/60"
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Filter Popover Button */}
          {visibleGroups.length > 0 && (
            <div className="relative shrink-0" ref={popoverRef}>
              <button
                type="button"
                onClick={() => setIsPopoverOpen((prev) => !prev)}
                title={t("Filter")}
                className={cn(
                  "inline-flex items-center gap-1 h-8 px-2 @[380px]/filter:px-2.5 text-[12.5px] rounded-[var(--radius-ctl)] border border-[var(--line)] transition-colors cursor-pointer select-none shrink-0",
                  activeFilterCount > 0
                    ? "bg-[var(--selected)] text-[var(--ink)] font-semibold border-[var(--ink-2)]"
                    : "bg-[var(--pane)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
                )}
                aria-expanded={isPopoverOpen}
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0" />
                <span className="hidden @[380px]/filter:inline">{t("Filter")}</span>
                {activeFilterCount > 0 && (
                  <span className="text-[10.5px] bg-[var(--ink)] text-white px-1.5 py-0.2 rounded-full tabular-nums">
                    {activeFilterCount}
                  </span>
                )}
                <ChevronDown className="hidden @[380px]/filter:inline w-3.5 h-3.5 text-[var(--ink-3)]" />
              </button>

              {/* Popover Dropdown: aligned safely inside narrow or wide containers */}
              {isPopoverOpen && (
                <div className="fixed left-4 right-4 @[360px]/filter:absolute @[360px]/filter:left-auto @[360px]/filter:right-0 @[360px]/filter:w-64 top-auto mt-1.5 p-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] shadow-xl z-50 text-[13px] space-y-3 animate-in fade-in zoom-in-95 duration-100">
                  <div className="flex items-center justify-between pb-1.5 border-b border-[var(--line)]">
                    <span className="font-semibold text-[var(--ink)] text-xs uppercase tracking-wider">
                      {t("Filters", "Filters")}
                    </span>
                    {activeFilterCount > 0 && onClearFilters && (
                      <button
                        type="button"
                        onClick={onClearFilters}
                        className="text-xs text-[var(--accent-ink)] hover:underline cursor-pointer"
                      >
                        {t("Reset all", "Alles herstellen")}
                      </button>
                    )}
                  </div>

                  <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                    {visibleGroups.map((group) => (
                      <div key={group.id} className="space-y-1">
                        <span className="text-xs font-semibold text-[var(--ink-3)]">
                          {group.title}
                        </span>
                        <div className="space-y-1 pt-0.5">
                          {group.options.map((opt) => {
                            const isSelected = selectedFilterIds.includes(opt.id);
                            return (
                              <label
                                key={opt.id}
                                className="flex items-center justify-between px-2 py-1 rounded hover:bg-[var(--selected)] cursor-pointer text-[var(--ink)] select-none"
                              >
                                <span className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => onFilterToggle?.(opt.id)}
                                    className="rounded border-[var(--line)] text-[var(--accent)] focus:ring-[var(--accent)]"
                                  />
                                  <span>{opt.label}</span>
                                </span>
                                {opt.count !== undefined && (
                                  <span className="text-xs text-[var(--ink-3)] tabular-nums">
                                    {opt.count}
                                  </span>
                                )}
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Optional Refresh icon button */}
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              title={refreshTooltip}
              className="w-8 h-8 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50 shrink-0"
            >
              <RotateCw
                className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin text-[var(--accent)]")}
              />
            </button>
          )}

          {/* Narrow container fallback for trailing controls (e.g. Split toggle / Compose) */}
          {trailingControl && (
            <div className="flex @[560px]/filter:hidden items-center gap-1 shrink-0">
              {trailingControl}
            </div>
          )}
        </div>
      </div>

      {/* Removable Active Filter Chips */}
      {activeFilterCount > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-3 pb-1 text-xs">
          <span className="text-[var(--ink-3)]">Active:</span>
          {visibleGroups.flatMap((group) =>
            group.options
              .filter((opt) => selectedFilterIds.includes(opt.id))
              .map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onFilterToggle?.(opt.id)}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--selected)] border border-[var(--line)] text-[var(--ink)] hover:border-[var(--ink-3)] transition-colors cursor-pointer"
                >
                  <span>{opt.label}</span>
                  <X className="w-3 h-3 text-[var(--ink-3)]" />
                </button>
              ))
          )}
          {onClearFilters && (
            <button
              type="button"
              onClick={onClearFilters}
              className="text-[var(--accent-ink)] hover:underline ml-1 cursor-pointer"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
