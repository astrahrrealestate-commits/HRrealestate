"use client";

import React, { useRef, useEffect } from "react";
import { Sparkles, Search, X, RotateCw, Home } from "lucide-react";
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
    <header className="h-14 bg-[#0D0F12] border-b border-transparent px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30 flex-shrink-0">
      {/* Left: Breadcrumbs matching reference design */}
      <div className="flex items-center gap-2.5">
        <Home className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
        <span className="text-zinc-400 text-xs font-normal">EstateOS</span>
        <span className="text-zinc-600 text-xs">/</span>
        <span className="text-white text-xs font-medium tracking-tight">
          {pageTitle || "Main Dashboard"}
        </span>
      </div>

      {/* Right: Sync Mailbox & Super Agent Core Button */}
      <div className="flex items-center gap-2.5 flex-shrink-0 ml-3">
        {/* Sync Mailbox button */}
        {onSyncMailbox && (
          <button
            type="button"
            onClick={onSyncMailbox}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 h-8 px-2.5 sm:px-3 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-zinc-300 text-[12px] font-medium transition-colors cursor-pointer disabled:opacity-50 select-none shadow-xs"
            title="Sync mailbox with Gmail & WhatsApp"
          >
            <RotateCw
              className={cn("w-3.5 h-3.5 text-zinc-400", isSyncing && "animate-spin text-orange-400")}
            />
            <span className="hidden sm:inline">Sync</span>
          </button>
        )}

        {/* Super Agent Core pill button */}
        <button
          type="button"
          onClick={onAskAgent || superAgent.toggleOpen}
          className={cn(
            "inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-white/10 bg-white/5 hover:bg-white/10 text-white text-[12.5px] font-medium transition-all cursor-pointer shadow-xs active:scale-[0.98] select-none",
            superAgent.isOpen && "border-orange-500 text-white bg-orange-500/20"
          )}
          title="Super Agent Core (Ctrl+J)"
        >
          <Sparkles className="w-3.5 h-3.5 text-orange-400 shrink-0" strokeWidth={2.25} />
          <span className="leading-none hidden sm:inline">Super Agent</span>
          <span className="text-[9.5px] font-mono uppercase px-1.5 py-0.5 rounded-full bg-white/10 text-zinc-300 font-semibold leading-none">
            Core
          </span>
        </button>
      </div>
    </header>
  );
}
