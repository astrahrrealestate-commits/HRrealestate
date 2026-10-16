"use client";

import React, { useState, useMemo, Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import {
  Bell,
  Sparkles,
  Radio,
  Sliders,
  ChevronRight,
  ArrowLeft,
  Check,
  ShieldCheck,
  Settings as SettingsIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { SETTING_GROUPS, SettingGroup, SettingItem } from "@/data/settingsMockData";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";

function SettingsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // URL state synchronization: ?group=id for mobile screen stack (Section 5.6.1)
  const groupParam = searchParams.get("group");

  const [selectedGroupId, setSelectedGroupId] = useState<string>(
    groupParam || SETTING_GROUPS[0].id
  );
  const [settingsState, setSettingsState] = useState<SettingGroup[]>(SETTING_GROUPS);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);

  // Sync state if URL changes
  useEffect(() => {
    if (groupParam && SETTING_GROUPS.some((g) => g.id === groupParam)) {
      setSelectedGroupId(groupParam);
    }
  }, [groupParam]);

  const activeGroup = useMemo(() => {
    return (
      settingsState.find((g) => g.id === selectedGroupId) ||
      settingsState[0]
    );
  }, [selectedGroupId, settingsState]);

  const handleToggle = (groupId: string, settingId: string) => {
    setSettingsState((prev) =>
      prev.map((g) => {
        if (g.id !== groupId) return g;
        return {
          ...g,
          settings: g.settings.map((s) => {
            if (s.id !== settingId) return s;
            return { ...s, currentValue: !s.currentValue };
          }),
        };
      })
    );
  };

  const handleSelectGroup = (groupId: string) => {
    setSelectedGroupId(groupId);
    // On mobile push group as its own screen (Section 5.6.1)
    if (window.innerWidth < 768) {
      router.push(`/settings?group=${groupId}`);
    }
  };

  const handleMobileBack = () => {
    router.push("/settings");
  };

  const isMobile = typeof window !== "undefined" && window.innerWidth < 768;
  const isMobileGroupScreen = Boolean(groupParam && isMobile);

  const getGroupIcon = (id: string) => {
    switch (id) {
      case "notifications":
        return Bell;
      case "ai-governance":
        return Sparkles;
      case "channels":
        return Radio;
      default:
        return Sliders;
    }
  };

  return (
    <div className="min-h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)]">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopCommandBar
          pageTitle="Settings"
          hideSearch={true}
          onAskAgent={() => setIsAskAgentOpen(true)}
        />

        {/* ------------------------------------------------------------- */}
        {/* DESKTOP LAYOUT (>= 768px): Two Columns (Groups on Left, Rows on Right) */}
        {/* ------------------------------------------------------------- */}
        <div className="hidden md:flex flex-1 overflow-hidden">
          
          {/* Column 1: Groups List (280px) */}
          <div className="w-[280px] shrink-0 border-r border-[var(--line)] bg-[var(--pane)] flex flex-col">
            <div className="p-4 border-b border-[var(--line)]">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                Configuration
              </span>
              <h2 className="text-[17px] font-heading font-semibold text-[var(--ink)] tracking-tight">
                System Settings
              </h2>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-[var(--line)]/60">
              {settingsState.map((group) => {
                const isSelected = group.id === activeGroup.id;
                const Icon = getGroupIcon(group.id);

                return (
                  <button
                    key={group.id}
                    onClick={() => handleSelectGroup(group.id)}
                    className={cn(
                      "w-full text-left p-4 transition-colors relative flex items-center justify-between cursor-pointer select-none",
                      isSelected
                        ? "bg-[var(--selected)] border-l-[3px] border-l-[var(--ink)]"
                        : "hover:bg-[var(--selected)]/40 border-l-[3px] border-l-transparent"
                    )}
                  >
                    <div className="flex items-center gap-3 min-w-0 pr-2">
                      <Icon className="w-4 h-4 text-[var(--ink-2)] shrink-0" />
                      <div className="min-w-0">
                        <span className="text-sm font-semibold text-[var(--ink)] block truncate">
                          {group.title}
                        </span>
                        <span className="text-xs text-[var(--ink-3)] block truncate">
                          {group.settings.length} rules
                        </span>
                      </div>
                    </div>

                    <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0" />
                  </button>
                );
              })}
            </div>
          </div>

          {/* Column 2: Full-width Settings Rows (flex-1) */}
          <div className="flex-1 bg-[var(--pane)] flex flex-col overflow-y-auto p-8 max-w-4xl space-y-6">
            
            {/* Group Header */}
            <div className="border-b border-[var(--line)] pb-5">
              <h2 className="text-[22px] font-heading font-bold text-[var(--ink)] tracking-tight">
                {activeGroup.title}
              </h2>
              <p className="text-xs sm:text-[13px] text-[var(--ink-2)] mt-1">
                {activeGroup.description}
              </p>
            </div>

            {/* Full-width Setting Rows (Section 5.6.1: Each setting a full-width row) */}
            <div className="divide-y divide-[var(--line)] border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] overflow-hidden shadow-2xs">
              {activeGroup.settings.map((setting) => (
                <div
                  key={setting.id}
                  className="p-5 flex items-center justify-between gap-4 hover:bg-[var(--selected)]/20 transition-colors"
                >
                  <div className="min-w-0 flex-1 pr-4">
                    <span className="text-sm font-semibold text-[var(--ink)] block">
                      {setting.title}
                    </span>
                    <p className="text-xs text-[var(--ink-3)] mt-0.5 leading-relaxed">
                      {setting.description}
                    </p>
                  </div>

                  {/* Setting Control */}
                  <div className="shrink-0">
                    {setting.valueType === "toggle" ? (
                      <button
                        onClick={() => handleToggle(activeGroup.id, setting.id)}
                        className={cn(
                          "w-11 h-6 rounded-full transition-colors relative cursor-pointer",
                          setting.currentValue ? "bg-[var(--ink)]" : "bg-[var(--line)]"
                        )}
                        aria-label={setting.title}
                      >
                        <span
                          className={cn(
                            "w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform",
                            setting.currentValue ? "right-0.5" : "left-0.5"
                          )}
                        />
                      </button>
                    ) : (
                      <span className="font-mono text-xs px-3 py-1.5 rounded-md border border-[var(--line)] bg-[var(--bg)] font-semibold text-[var(--ink)]">
                        {setting.currentValue}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Compliance Note */}
            <div className="text-xs text-[var(--ink-3)] flex items-center gap-1.5 pt-2">
              <ShieldCheck className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>EstateOS policies comply with Dutch Tenancy Law (Burgerlijk Wetboek Boek 7)</span>
            </div>

          </div>

        </div>

        {/* ------------------------------------------------------------- */}
        {/* MOBILE LAYOUT (< 768px): One Column, Groups open as screens  */}
        {/* ------------------------------------------------------------- */}
        <div className="md:hidden flex-1 flex flex-col min-w-0">

          {/* SCREEN 1: Mobile Settings Group List (when ?group is not set) */}
          {!isMobileGroupScreen && (
            <div className="flex-1 flex flex-col bg-[var(--bg)] pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
              <div className="p-4 border-b border-[var(--line)] bg-[var(--pane)]">
                <span className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-3)] block mb-1">
                  Settings Directory
                </span>
                <div className="text-[15px] font-semibold text-[var(--ink)]">
                  Portfolio System Preferences
                </div>
              </div>

              {/* Group full-width rows */}
              <div className="divide-y divide-[var(--line)] bg-[var(--pane)]">
                {settingsState.map((group) => {
                  const Icon = getGroupIcon(group.id);

                  return (
                    <button
                      key={group.id}
                      onClick={() => handleSelectGroup(group.id)}
                      className="w-full text-left p-4 flex items-center justify-between hover:bg-[var(--selected)]/40 active:bg-[var(--selected)] transition-colors cursor-pointer select-none min-h-[64px]"
                    >
                      <div className="flex items-center gap-3.5 min-w-0 pr-2">
                        <Icon className="w-5 h-5 text-[var(--ink-2)] shrink-0" />
                        <div className="min-w-0">
                          <span className="font-semibold text-[15px] text-[var(--ink)] block truncate">
                            {group.title}
                          </span>
                          <span className="text-xs text-[var(--ink-3)] block truncate mt-0.5">
                            {group.description}
                          </span>
                        </div>
                      </div>

                      <ChevronRight className="w-4 h-4 text-[var(--ink-3)] shrink-0 ml-1" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* SCREEN 2: Mobile Group Screen (when ?group=id is set) */}
          {isMobileGroupScreen && (
            <div className="flex-1 flex flex-col bg-[var(--bg)] h-full pb-[calc(4.5rem+env(safe-area-inset-bottom))]">
              {/* Header with Back Arrow to Settings List */}
              <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    onClick={handleMobileBack}
                    className="p-1 -ml-1 text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer"
                    aria-label="Back to settings directory"
                  >
                    <ArrowLeft className="w-5 h-5" />
                  </button>
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-bold text-[var(--ink)] truncate">
                      {activeGroup.title}
                    </h2>
                    <p className="text-[11px] text-[var(--ink-3)] truncate">
                      {activeGroup.settings.length} rules
                    </p>
                  </div>
                </div>
              </div>

              {/* Group Full-width Rows */}
              <div className="flex-1 overflow-y-auto divide-y divide-[var(--line)] bg-[var(--pane)]">
                {activeGroup.settings.map((setting) => (
                  <div
                    key={setting.id}
                    className="p-4 flex items-center justify-between gap-3 min-h-[64px]"
                  >
                    <div className="min-w-0 flex-1 pr-2">
                      <span className="font-semibold text-[14px] text-[var(--ink)] block leading-tight">
                        {setting.title}
                      </span>
                      <p className="text-xs text-[var(--ink-3)] mt-1 leading-relaxed">
                        {setting.description}
                      </p>
                    </div>

                    <div className="shrink-0">
                      {setting.valueType === "toggle" ? (
                        <button
                          onClick={() => handleToggle(activeGroup.id, setting.id)}
                          className={cn(
                            "w-11 h-6 rounded-full transition-colors relative cursor-pointer",
                            setting.currentValue ? "bg-[var(--ink)]" : "bg-[var(--line)]"
                          )}
                          aria-label={setting.title}
                        >
                          <span
                            className={cn(
                              "w-5 h-5 bg-white rounded-full absolute top-0.5 transition-transform",
                              setting.currentValue ? "right-0.5" : "left-0.5"
                            )}
                          />
                        </button>
                      ) : (
                        <span className="font-mono text-xs px-2.5 py-1 rounded border border-[var(--line)] bg-[var(--bg)] font-semibold text-[var(--ink)]">
                          {setting.currentValue}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>

      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* 4. Ask EstateOS Side Panel */}
      <AskEstateOSPanel
        isOpen={isAskAgentOpen}
        onClose={() => setIsAskAgentOpen(false)}
        currentPageName="Settings"
        selectedContext={`Settings Section: ${activeGroup.title}`}
      />
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Settings...</div>}>
      <SettingsContent />
    </Suspense>
  );
}
