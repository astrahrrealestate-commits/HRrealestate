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
    <header className="h-[48px] bg-[#1B1B1B] border-b border-[#27272a] px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30 shrink-0">
      {/* Left: Breadcrumbs matching reference design */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-[#94a3b8] font-normal">EstateOS</span>
        <span className="text-[#64748b]">/</span>
        <span className="text-white font-medium tracking-tight">
          {pageTitle || "Main Dashboard"}
        </span>
      </div>

      {/* Right: Sync Mailbox & Super Agent Core Button */}
      <div className="flex items-center gap-2 flex-shrink-0 ml-3">
        {/* Sync Mailbox button */}
        {onSyncMailbox && (
          <button
            type="button"
            onClick={onSyncMailbox}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 h-[30px] px-2.5 sm:px-3 rounded-full text-xs font-semibold bg-white/10 hover:bg-white/15 text-white border border-white/15 transition-all cursor-pointer disabled:opacity-50 select-none"
            title="Sync mailbox with Gmail & WhatsApp"
          >
            <RotateCw
              className={cn("w-3.5 h-3.5 text-zinc-300", isSyncing && "animate-spin text-[#1a73e8]")}
            />
            <span className="hidden sm:inline">Sync</span>
          </button>
        )}

        {/* Super Agent Core pill button */}
        <button
          type="button"
          onClick={onAskAgent || superAgent.toggleOpen}
          className={cn(
            "inline-flex items-center gap-1.5 h-[30px] px-3 rounded-full text-xs font-semibold transition-all cursor-pointer select-none",
            superAgent.isOpen
              ? "bg-[#1a73e8] text-white shadow-[0_0_12px_rgba(26,115,232,0.4)]"
              : "bg-white/10 hover:bg-white/15 text-white border border-white/15"
          )}
          title="Super Agent Core (Ctrl+J)"
        >
          <Sparkles className={cn("w-3.5 h-3.5 text-[#1a73e8] shrink-0", superAgent.isOpen && "text-white animate-ai-star")} strokeWidth={2.25} />
          <span className="leading-none hidden sm:inline">Super Agent</span>
          <span className="text-[10px] uppercase font-mono px-1.5 py-0.2 rounded-full bg-white/20 text-white ml-0.5">
            Core
          </span>
        </button>
      </div>
    </header>
  );
}
