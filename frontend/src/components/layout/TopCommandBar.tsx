"use client";

import React, { useRef, useEffect } from "react";
import Image from "next/image";
import { Search, X, RotateCw } from "lucide-react";
import { AstraIcon, AstraWordmark } from "@/components/ui/AstraBrand";
import { cn } from "@/lib/utils";
import { useSuperAgent } from "@/context/SuperAgentContext";
import { useLanguage } from "@/context/LanguageContext";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";
import { useAuth } from "@/context/AuthContext";

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
  const { language, setLanguage, t } = useLanguage();
  const { canUseAgent } = useAuth();
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
    <header className="h-[52px] bg-[#0A1B2F] border-b border-[#162B45] px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30 shrink-0">
      {/* Left: Clean Page Title */}
      <div className="flex items-center gap-2.5 text-xs min-w-0">
        {/* Mobile-only Brand Mark (only visible on mobile where the sidebar is hidden) */}
        <span className="md:hidden flex items-center gap-2 shrink-0">
          <Image
            src="/images/hr-realestate-mark.png"
            alt="HR Real Estate"
            width={22}
            height={22}
            className="w-5.5 h-5.5 object-contain shrink-0"
          />
          <span className="text-[#334b6b] shrink-0 font-light">/</span>
        </span>

        {/* Page Title */}
        <span className="text-white font-semibold tracking-tight truncate text-[14px]">
          {pageTitle ? t(pageTitle, pageTitle) : t("topbar.control_center")}
        </span>
      </div>

      {/* Right: Language Switcher, Sync Mailbox & Super Agent Core Button */}
      <div className="flex items-center gap-2 flex-shrink-0 ml-3">
        {/* Language Segmented Toggle (EN / NL) */}
        <div className="flex items-center rounded-full bg-[#10213B] border border-[#162B45] p-0.5 text-[11px] font-semibold text-slate-400">
          <button
            type="button"
            onClick={() => setLanguage("en")}
            className={cn(
              "px-2.5 py-1 rounded-full transition-all cursor-pointer flex items-center gap-1.5",
              language === "en"
                ? "bg-white/20 text-white shadow-xs font-bold"
                : "hover:text-slate-200"
            )}
            title="English"
          >
            <FlagUK className="w-3.5 h-2.5" />
            <span>EN</span>
          </button>
          <button
            type="button"
            onClick={() => setLanguage("nl")}
            className={cn(
              "px-2.5 py-1 rounded-full transition-all cursor-pointer flex items-center gap-1.5",
              language === "nl"
                ? "bg-white/20 text-white shadow-xs font-bold"
                : "hover:text-slate-200"
            )}
            title="Nederlands"
          >
            <FlagNL className="w-3.5 h-2.5" />
            <span>NL</span>
          </button>
        </div>

        {/* Sync Mailbox button */}
        {onSyncMailbox && (
          <button
            type="button"
            onClick={onSyncMailbox}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 h-[30px] px-2.5 sm:px-3 rounded-full text-xs font-semibold bg-white/10 hover:bg-white/15 text-white border border-[#162B45] transition-all cursor-pointer disabled:opacity-50 select-none"
            title={t("topbar.sync_tooltip")}
          >
            <RotateCw
              className={cn("w-3.5 h-3.5 text-zinc-300", isSyncing && "animate-spin text-[#1a73e8]")}
            />
            <span className="hidden sm:inline">
              {isSyncing ? t("topbar.syncing") : t("topbar.sync")}
            </span>
          </button>
        )}

        {/* Super Agent Core pill button (hidden for profiles that do not open every section) */}
        {canUseAgent && (
        <button
          type="button"
          onClick={onAskAgent || superAgent.toggleOpen}
          className={cn(
            "inline-flex items-center gap-1.5 h-[30px] px-3 rounded-full text-xs font-semibold transition-all cursor-pointer select-none border",
            superAgent.isOpen
              ? "bg-[#10213B] text-white border-[#162B45] shadow-[0_0_12px_rgba(0,229,255,0.25)]"
              : "bg-white/10 hover:bg-white/15 text-white border-white/15"
          )}
          title={t("topbar.agent_shortcut")}
        >
          <AstraIcon className={cn("w-3.5 h-3.5 text-[#38bdf8] shrink-0", superAgent.isOpen && "animate-ai-star")} />
          <AstraWordmark variant="dark" className="text-[11px] hidden sm:inline" />
          <span className="text-[10px] font-semibold px-1.5 py-0.2 rounded-full bg-white/20 text-white ml-0.5">
            {t("topbar.agent_active")}
          </span>
        </button>
        )}
      </div>
    </header>
  );
}
