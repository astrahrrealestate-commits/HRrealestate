"use client";

import React, { useState, useEffect } from "react";
import { ConnectionsModal } from "@/components/connections/ConnectionsModal";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Inbox,
  Wrench,
  Building2,
  MoreHorizontal,
  Users,
  Contact,
  Coins,
  BarChart3,
  FileSpreadsheet,
  BookOpen,
  Settings,
  ShieldCheck,
  LayoutGrid,
  LogOut,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { needsYouCount, ThreadCountTarget } from "@/lib/selectors";
import { useLanguage } from "@/context/LanguageContext";
import { useAuth } from "@/context/AuthContext";

interface MobileTabBarProps {
  pendingCount?: number;
  threads?: ThreadCountTarget[];
  className?: string;
}

export function MobileTabBar({ pendingCount, threads, className }: MobileTabBarProps) {
  const pathname = usePathname() || "/";
  const { t } = useLanguage();
  const { user, logout, canAccess } = useAuth();
  const displayName = user?.name || "Harjot Singh";
  const displayEmail = user?.email || "harjot@estateos.internal";
  const userInitials = displayName
    .split(/\s+/)
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [isConnectionsOpen, setIsConnectionsOpen] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (
        params.get("connections") === "open" ||
        params.get("google_connected") ||
        params.get("google_error")
      ) {
        setIsConnectionsOpen(true);
      }
    }
  }, []);

  // Section 6.4: Single source of truth for nav count
  const effectiveCount =
    pendingCount !== undefined
      ? pendingCount
      : needsYouCount(threads || []);

  const mainTabs = [
    { label: t("nav.dashboard") || "Today", section: "dashboard", href: "/", icon: Home },
    {
      label: t("nav.messages") || "Inbox",
      section: "inbox",
      href: "/inbox",
      icon: Inbox,
      badge: effectiveCount > 0 ? effectiveCount : undefined,
    },
    { label: t("nav.maintenance") || "Maintenance", section: "maintenance", href: "/maintenance", icon: Wrench },
    { label: t("nav.properties") || "Properties", section: "properties", href: "/properties", icon: Building2 },
  ].filter((tab) => canAccess(tab.section));

  const moreItems = [
    { label: t("nav.tenants") || "Tenants", section: "tenants", href: "/tenants", icon: Users },
    { label: t("nav.contacts") || "Contacts", section: "contacts", href: "/contacts", icon: Contact },
    { label: "Money", section: "money", href: "/money", icon: Coins },
    { label: t("nav.reports") || "Reports", section: "reports", href: "/reports", icon: FileSpreadsheet },
    { label: t("nav.knowledge_base") || "Knowledge Base", section: "reports", href: "/knowledge", icon: BookOpen },
    ...(user?.isAdmin ? [{ label: "Team & access", section: "admin", href: "/admin", icon: ShieldCheck }] : []),
  ].filter((item) => canAccess(item.section));

  const isMoreActive = moreItems.some((item) => pathname.startsWith(item.href));

  return (
    <>
      {/* Bottom Tab Bar (Section 5.6): height 56px + safe-area-inset, md:hidden */}
      <nav
        className={cn(
          "fixed inset-x-0 bottom-0 z-40 grid border-t border-[var(--line)] bg-[var(--pane)] pb-[env(safe-area-inset-bottom)] md:hidden select-none",
          className
        )}
        style={{ gridTemplateColumns: `repeat(${mainTabs.length + 1}, minmax(0, 1fr))` }}
      >
        {mainTabs.map((tab) => {
          const isActive =
            tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
          const Icon = tab.icon;

          return (
            <Link
              key={tab.label}
              href={tab.href}
              className={cn(
                "flex flex-col items-center justify-center h-14 relative transition-colors",
                isActive
                  ? "text-[var(--ink)] font-semibold"
                  : "text-[var(--ink-3)] hover:text-[var(--ink)] font-normal"
              )}
            >
              <div className="relative">
                <Icon className="w-5 h-5" strokeWidth={isActive ? 2.25 : 1.75} />
                {tab.badge !== undefined && (
                  <span className="absolute -top-1.5 -right-3 bg-[var(--accent)] text-[#0A0A0A] text-[10px] font-bold px-1.5 py-0.2 rounded-full leading-none tabular-nums">
                    {tab.badge}
                  </span>
                )}
              </div>
              <span className="text-[10.5px] mt-1 leading-none">{tab.label}</span>
            </Link>
          );
        })}

        {/* More Tab Button */}
        <button
          type="button"
          onClick={() => setIsMoreOpen(true)}
          className={cn(
            "flex flex-col items-center justify-center h-14 relative transition-colors cursor-pointer",
            isMoreOpen || isMoreActive
              ? "text-[var(--ink)] font-semibold"
              : "text-[var(--ink-3)] hover:text-[var(--ink)] font-normal"
          )}
        >
          <MoreHorizontal className="w-5 h-5" strokeWidth={isMoreActive ? 2.25 : 1.75} />
          <span className="text-[10.5px] mt-1 leading-none">More</span>
        </button>
      </nav>

      {/* More Bottom Sheet Drawer */}
      {isMoreOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex flex-col justify-end">
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
            onClick={() => setIsMoreOpen(false)}
          />

          {/* Bottom Sheet Modal */}
          <div className="relative w-full bg-[var(--pane)] border-t border-[var(--line)] rounded-t-[18px] p-5 pb-[max(1.5rem,calc(env(safe-area-inset-bottom)+1rem))] space-y-4 shadow-xl animate-in slide-in-from-bottom duration-200">
            {/* Header */}
            <div className="flex items-center justify-between pb-3 border-b border-[var(--line)]">
              <span className="font-heading font-bold text-[16px] text-[var(--ink)]">
                More Pages
              </span>
              <button
                type="button"
                onClick={() => setIsMoreOpen(false)}
                className="p-1 rounded-[var(--radius-ctl)] text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Grid of items */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setIsMoreOpen(false);
                  setIsConnectionsOpen(true);
                }}
                className="flex items-center gap-3 p-3 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] text-[var(--ink-2)] hover:bg-[var(--selected)] transition-colors text-left cursor-pointer col-span-2"
              >
                <LayoutGrid className="w-4 h-4 text-emerald-600" strokeWidth={1.75} />
                <div className="flex items-center justify-between flex-1">
                  <span className="text-[13px] font-medium text-[var(--ink)]">Connections</span>
                  <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                    Active
                  </span>
                </div>
              </button>
              {moreItems.map((item) => {
                const isActive = pathname.startsWith(item.href);
                const Icon = item.icon;

                return (
                  <Link
                    key={item.label}
                    href={item.href}
                    onClick={() => setIsMoreOpen(false)}
                    className={cn(
                      "flex items-center gap-3 p-3 rounded-[var(--radius-ctl)] border border-[var(--line)] transition-colors",
                      isActive
                        ? "bg-[var(--selected)] text-[var(--ink)] font-semibold border-[var(--ink)]"
                        : "bg-[var(--pane)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
                    )}
                  >
                    <Icon className="w-4 h-4 text-[var(--ink)]" strokeWidth={1.75} />
                    <span className="text-[13px]">{item.label}</span>
                  </Link>
                );
              })}
            </div>

            {/* Account & Sign Out */}
            <div className="pt-3 border-t border-[var(--line)] space-y-2.5">
              <div className="flex items-center justify-between gap-3 px-1">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-[#0A1B2F] text-white flex items-center justify-center text-xs font-bold shrink-0">
                    {userInitials}
                  </div>
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-[var(--ink)] truncate leading-tight">
                      {displayName}
                    </div>
                    <div className="text-[11px] text-[var(--ink-3)] truncate font-mono leading-tight mt-0.5">
                      {displayEmail}
                    </div>
                  </div>
                </div>
                <span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wider bg-[#EFF6FF] text-[#1a73e8] border border-[#BFDBFE] shrink-0">
                  {user?.role || "Owner"}
                </span>
              </div>

              <button
                type="button"
                onClick={() => {
                  setIsMoreOpen(false);
                  void logout();
                }}
                className="w-full flex items-center justify-center gap-2 py-2.5 px-3 rounded-[var(--radius-ctl)] border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-100 active:bg-rose-100 text-[13px] font-semibold transition-colors cursor-pointer"
              >
                <LogOut className="w-4 h-4 shrink-0" strokeWidth={2} />
                <span>{t("nav.sign_out") || "Sign out"}</span>
              </button>
            </div>

            {/* Prototype sample data notice at the bottom of the sheet (Section 5.6) */}
            <div className="pt-1 text-center text-xs text-[var(--ink-3)]">
              Prototype · sample data
            </div>
          </div>
        </div>
      )}
      <ConnectionsModal isOpen={isConnectionsOpen} onClose={() => setIsConnectionsOpen(false)} />
    </>
  );
}
