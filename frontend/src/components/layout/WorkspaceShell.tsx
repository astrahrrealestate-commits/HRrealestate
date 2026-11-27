"use client";

import React, { useEffect } from "react";
import { setPageNeedsYou } from "@/lib/needsYou";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { cn } from "@/lib/utils";

export interface WorkspaceShellProps {
  pageTitle: string;
  pendingCount?: number;
  onSyncMailbox?: () => void;
  isSyncing?: boolean;
  searchQuery?: string;
  onSearchChange?: (q: string) => void;
  hideSearch?: boolean;
  agentPageName?: string;
  agentContext?: string;
  onAgentAction?: (actionType: string, payload?: unknown) => void;
  hideMobileTabBar?: boolean;
  hideTopBarOnMobile?: boolean;
  cardClassName?: string;
  children: React.ReactNode;
}

/**
 * Shared desktop & mobile application shell across all EstateOS pages.
 * Provides the TopCommandBar, framed content card,
 * drag-resizable AskEstateOSPanel (Astra), and MobileTabBar.
 */
export function WorkspaceShell({
  pageTitle,
  pendingCount,
  onSyncMailbox,
  isSyncing,
  searchQuery,
  onSearchChange,
  hideSearch = true,
  agentPageName,
  agentContext,
  onAgentAction,
  hideMobileTabBar = false,
  hideTopBarOnMobile = false,
  cardClassName,
  children,
}: WorkspaceShellProps) {
  // The sidebar lives outside the page (AppFrame): hand it this page's own count while the page is open.
  useEffect(() => {
    setPageNeedsYou(pendingCount ?? null);
    return () => setPageNeedsYou(null);
  }, [pendingCount]);

  return (
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <div className={cn(hideTopBarOnMobile ? "hidden md:block shrink-0" : "block shrink-0")}>
          <TopCommandBar
            pageTitle={pageTitle}
            hideSearch={hideSearch}
            searchQuery={searchQuery}
            onSearchChange={onSearchChange}
            onSyncMailbox={onSyncMailbox}
            isSyncing={isSyncing}
          />
        </div>

        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div
            className={cn(
              "flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#162B45] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative min-w-0",
              cardClassName
            )}
          >
            {children}
          </div>

          <AskEstateOSPanel
            currentPageName={agentPageName || pageTitle}
            selectedContext={agentContext}
            onActionTriggered={onAgentAction}
          />
        </div>
      </div>

      {!hideMobileTabBar && <MobileTabBar pendingCount={pendingCount} />}
    </div>
  );
}
