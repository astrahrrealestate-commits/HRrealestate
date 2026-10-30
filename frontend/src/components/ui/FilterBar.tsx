"use client";

import React, { useState, useRef, useEffect } from "react";
import { Search, ChevronDown, RotateCw, X, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";

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
  onRefresh?: () => void;
  isRefreshing?: boolean;
  refreshTooltip?: string;
  searchPlaceholder?: string;
  className?: string;
}

/**
 * FilterBar implements Section 4 & Section 5.2:
 * - 3 View tabs: e.g. [ Needs you 4 ] [ All ] [ Done ]
 * - Search input with keyboard shortcut '/'
 * - Single "Filter ▾" button opening a popover with checkbox groups (hiding 0 count items)
 * - Single icon-only Refresh button (⟳) with tooltip
 * - Active filter removable chips displayed when filters are set
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
  onRefresh,
  isRefreshing = false,
  refreshTooltip = "Sync mailbox",
  searchPlaceholder = "Search...",
  className,
}: FilterBarProps) {
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close popover when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setIsPopoverOpen(false);
      }
    }
    if (isPopoverOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isPopoverOpen]);

  // Global '/' keyboard shortcut to focus search
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

  // Filter groups with > 0 items only (Section 5.2: "Never show options with count 0")
  const visibleGroups = filterGroups.map((group) => ({
    ...group,
    options: group.options.filter((opt) => opt.count === undefined || opt.count > 0),
  })).filter((group) => group.options.length > 0);

  const activeFilterCount = selectedFilterIds.length;

  return (
    <div className={cn("flex flex-col gap-2 w-full", className)}>
      {/* Main Bar: Tabs | Search | Filter ▾ | ⟳ */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-[var(--pane)] border-b border-[var(--line)]">
        {/* Left: View Tabs */}
        <div className="flex items-center gap-1">
          {tabs.map((tab) => {
            const isActive = tab.id === activeTab;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-ctl)] text-[13px] font-medium transition-colors cursor-pointer select-none",
                  isActive
                    ? "bg-[var(--selected)] text-[var(--ink)] font-semibold"
                    : "text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)]/50"
                )}
              >
                <span>{tab.label}</span>
                {tab.count !== undefined && (
                  <span
                    className={cn(
                      "text-xs px-1.5 py-0.2 rounded-full tabular-nums",
                      tab.id === "needs_you" || tab.id === "needs_action"
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

        {/* Right: Search + Filter popover + Refresh */}
        <div className="flex items-center gap-2 flex-1 sm:flex-initial justify-end">
          {/* Search box */}
          <div className="relative flex-1 sm:w-56 md:w-64">
            <Search className="w-4 h-4 text-[var(--ink-3)] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              className="w-full h-8 pl-8 pr-7 text-[13px] bg-[var(--bg)] border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)] transition-colors"
            />
            {searchQuery ? (
              <button
                type="button"
                onClick={() => onSearchChange("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--ink-3)] hover:text-[var(--ink)] p-0.5"
                title="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            ) : (
              <kbd className="hidden sm:inline-block absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[var(--ink-3)] border border-[var(--line)] bg-[var(--pane)] px-1 rounded">
                /
              </kbd>
            )}
          </div>

          {/* Filter Popover Button */}
          {visibleGroups.length > 0 && (
            <div className="relative" ref={popoverRef}>
              <button
                type="button"
                onClick={() => setIsPopoverOpen((prev) => !prev)}
                className={cn(
                  "inline-flex items-center gap-1.5 h-8 px-2.5 text-[13px] rounded-[var(--radius-ctl)] border border-[var(--line)] transition-colors cursor-pointer select-none",
                  activeFilterCount > 0
                    ? "bg-[var(--selected)] text-[var(--ink)] font-semibold border-[var(--ink-2)]"
                    : "bg-[var(--pane)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
                )}
                aria-expanded={isPopoverOpen}
              >
                <SlidersHorizontal className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                <span>Filter</span>
                {activeFilterCount > 0 && (
                  <span className="text-xs bg-[var(--ink)] text-white px-1.5 py-0.2 rounded-full tabular-nums">
                    {activeFilterCount}
                  </span>
                )}
                <ChevronDown className="w-3.5 h-3.5 text-[var(--ink-3)]" />
              </button>

              {/* Popover Dropdown */}
              {isPopoverOpen && (
                <div className="absolute right-0 top-full mt-1.5 w-64 p-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] shadow-md z-50 text-[13px] space-y-3 animate-in fade-in zoom-in-95 duration-100">
                  <div className="flex items-center justify-between pb-1.5 border-b border-[var(--line)]">
                    <span className="font-semibold text-[var(--ink)] text-xs uppercase tracking-wider">
                      Filters
                    </span>
                    {activeFilterCount > 0 && onClearFilters && (
                      <button
                        type="button"
                        onClick={onClearFilters}
                        className="text-xs text-[var(--accent-ink)] hover:underline cursor-pointer"
                      >
                        Reset all
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

          {/* Refresh icon button (⟳) with tooltip */}
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              title={refreshTooltip}
              className="w-8 h-8 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50"
            >
              <RotateCw
                className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin text-[var(--accent)]")}
              />
            </button>
          )}
        </div>
      </div>

      {/* Removable Active Filter Chips (Section 4) */}
      {activeFilterCount > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-4 text-xs">
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
