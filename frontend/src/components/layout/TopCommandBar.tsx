"use client";

import React, { useRef, useEffect } from "react";
import { Sparkles, Search, X, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSuperAgent } from "@/context/SuperAgentContext";

interface TopCommandBarProps {
  onAskAgent?: () => void;
  onSyncMailbox?: () => void;
  isSyncing?: boolean;
  searchQuery?: string;
  onSearchChange?: (q: string) => void;
  pageTitle?: string;
  hideSearch?: boolean;
}

/**
 * TopCommandBar implements Sections 2.1 (G1, G2, G3), 5.1 & 5.6:
 * - Height: h-14 (56px) sticky top-0 (G2: fixes title clipping)
 * - Removed duplicate top connected strip (G1: keeps only sidebar connected block)
 * - Global search with '/' keyboard shortcut (suppressed when hideSearch is true)
 * - Muted "Prototype · sample data" tag (hidden on mobile, G1 & 5.6)
 * - Restyled "Ask EstateOS" button (G3):
 *   - Desktop: White pill, 1px line border, orange sparkle, ink text
 *   - Mobile: Icon-only orange sparkle button (5.6)
 */
export function TopCommandBar({
  onAskAgent,
  onSyncMailbox,
  isSyncing = false,
  searchQuery,
  onSearchChange,
  pageTitle,
  hideSearch = false,
}: TopCommandBarProps) {
  const superAgent = useSuperAgent();
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA"].includes((event.target as HTMLElement)?.tagName)
      ) {
        if (!hideSearch && onSearchChange && searchInputRef.current) {
          event.preventDefault();
          searchInputRef.current.focus();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [hideSearch, onSearchChange]);

  return (
    <header className="h-14 border-b border-[var(--line)] bg-[var(--pane)] px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30">
      {/* Left: Global Search or Page Title */}
      <div className="flex items-center gap-3 flex-1 max-w-md">
        {hideSearch ? (
          pageTitle && (
            <span className="font-heading font-bold text-[17px] text-[var(--ink)] tracking-tight">
              {pageTitle}
            </span>
          )
        ) : (
          <>
            {pageTitle && (
              <span className="md:hidden font-heading font-bold text-[16px] text-[var(--ink)] truncate">
                {pageTitle}
              </span>
            )}

            {onSearchChange ? (
              <div className="relative w-full max-w-xs sm:max-w-sm">
                <Search className="w-4 h-4 text-[var(--ink-3)] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery || ""}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder="Search (press /)..."
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
            ) : (
              <div className="relative w-full max-w-xs sm:max-w-sm">
                <Search className="w-4 h-4 text-[var(--ink-3)] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  placeholder="Search EstateOS (press /)..."
                  disabled
                  className="w-full h-8 pl-8 pr-7 text-[13px] bg-[var(--bg)]/60 border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink-3)] cursor-not-allowed"
                />
                <kbd className="hidden sm:inline-block absolute right-2 top-1/2 -translate-y-1/2 text-[10px] font-mono text-[var(--ink-3)] border border-[var(--line)] bg-[var(--pane)] px-1 rounded">
                  /
                </kbd>
              </div>
            )}
          </>
        )}
      </div>

      {/* Right: Prototype sample data notice & Sync Mailbox & Ask EstateOS Button */}
      <div className="flex items-center gap-2.5 flex-shrink-0 ml-3">
        <span className="text-[12px] text-[var(--ink-3)] font-normal hidden lg:inline-block">
          Prototype · sample data
        </span>

        {/* Sync Mailbox button */}
        {onSyncMailbox && (
          <button
            type="button"
            onClick={onSyncMailbox}
            disabled={isSyncing}
            className={cn(
              "inline-flex items-center gap-1.5 h-8 px-2.5 sm:px-3 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink)] text-[12.5px] font-medium transition-colors cursor-pointer disabled:opacity-50 select-none shadow-2xs"
            )}
            title="Sync mailbox with Gmail & WhatsApp"
          >
            <RotateCw
              className={cn("w-3.5 h-3.5 text-[var(--ink-2)]", isSyncing && "animate-spin text-[var(--accent)]")}
            />
            <span className="hidden sm:inline">Sync mailbox</span>
          </button>
        )}

        {/* Restyled Ask EstateOS Button (Section 2.1 G3 & 5.6):
            - Desktop: White pill, 1px line border, orange sparkle, ink text
            - Mobile: Icon-only orange sparkle button */}
        <button
          type="button"
          onClick={onAskAgent || superAgent.toggleOpen}
          className={cn(
            "inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink)] text-[13px] font-medium transition-all cursor-pointer shadow-xs active:scale-[0.98] select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]",
            superAgent.isOpen && "border-[var(--accent)] text-[var(--accent-ink)] bg-[var(--accent)]/10"
          )}
          title="Ask EstateOS Assistant (Ctrl+J)"
        >
          <Sparkles className="w-3.5 h-3.5 text-[var(--accent)] shrink-0" strokeWidth={2.25} />
          <span className="leading-none hidden sm:inline">Ask EstateOS</span>
        </button>
      </div>
    </header>
  );
}
