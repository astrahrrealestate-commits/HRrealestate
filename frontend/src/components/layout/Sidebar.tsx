"use client";

import React, { useState, useEffect } from "react";
import { ConnectionsModal } from "@/components/connections/ConnectionsModal";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Inbox,
  Building2,
  Users,
  Contact,
  Wrench,
  CircleDollarSign,
  LayoutGrid,
  BookOpen,
  ChevronDown,
  LogOut,
  Search,
  ShieldCheck,
  UserPlus,
  Coins,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { needsYouCount, ThreadCountTarget } from "@/lib/selectors";
import { getInboxThreads } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useLanguage } from "@/context/LanguageContext";
import { useSuperAgent } from "@/context/SuperAgentContext";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  badge?: number | string;
}

interface SidebarProps {
  pendingCount?: number;
  threads?: ThreadCountTarget[];
}

export function Sidebar({ pendingCount, threads }: SidebarProps) {
  const pathname = usePathname() || "/";
  const [isConnectionsOpen, setIsConnectionsOpen] = useState(false);
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);

  // Auto-open Connections modal if returning from OAuth
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
  const { user, logout, canAccess } = useAuth();
  const { t } = useLanguage();
  const { isOpen: isSuperAgentOpen } = useSuperAgent();
  const compact = isSuperAgentOpen;

  const displayName = user?.name || "Harjot Singh";
  const displayEmail = user?.email || "harjot@estateos.internal";
  const userInitials = displayName
    .split(/\s+/)
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const [liveCount, setLiveCount] = useState<number | null>(null);

  // When not provided by parent page, query live inbox threads once
  useEffect(() => {
    if (pendingCount !== undefined || threads !== undefined) return;
    let isMounted = true;
    getInboxThreads()
      .then(({ threads: liveThreads }) => {
        if (isMounted && Array.isArray(liveThreads)) {
          setLiveCount(needsYouCount(liveThreads));
        }
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, [pendingCount, threads]);

  // Single source of truth for nav count
  const effectiveCount =
    pendingCount !== undefined
      ? pendingCount
      : threads !== undefined
      ? needsYouCount(threads)
      : liveCount !== null
      ? liveCount
      : 0;

  const allNavigationItems: (NavItem & { section: string })[] = [
    {
      label: t("nav.dashboard") || "Dashboard",
      section: "dashboard",
      href: "/",
      icon: Home,
      badge: effectiveCount > 0 ? `(${effectiveCount} ${t("nav.today_badge") || "Today"})` : undefined,
    },
    {
      label: t("nav.messages") || "Messages",
      section: "inbox",
      href: "/inbox",
      icon: Inbox,
      badge: effectiveCount > 0 ? `(${effectiveCount})` : undefined,
    },
    { label: t("nav.properties") || "Properties", section: "properties", href: "/properties", icon: Building2 },
    { label: t("nav.tenants") || "Tenants", section: "tenants", href: "/tenants", icon: Users },
    { label: t("nav.contacts") || "Contacts", section: "contacts", href: "/contacts", icon: Contact },
    { label: t("nav.maintenance") || "Maintenance", section: "maintenance", href: "/maintenance", icon: Wrench },
    { label: t("nav.money") || "Money", section: "money", href: "/money", icon: CircleDollarSign },
  ];
  const navigationItems = allNavigationItems.filter((item) => canAccess(item.section));

  return (
    <aside
      className={cn(
        "hidden md:flex flex-col justify-between select-none h-dvh sticky top-0 flex-shrink-0 border-r border-[#162B45] bg-[#0A1B2F] transition-all duration-200 z-20",
        compact ? "md:w-[68px]" : "md:w-[72px] xl:w-[240px]"
      )}
    >
      {/* Top Header & Navigation */}
      <div className="flex flex-col">
        {/* Brand Logo Header (h-14 aligned with TopCommandBar) */}
        <div
          className={cn(
            "h-[48px] flex items-center border-b border-[#162B45]",
            compact ? "px-0 justify-center" : "px-4 xl:px-4 justify-between"
          )}
        >
          <Link href="/" className="flex items-center gap-2.5 group" title="EstateOS">
            <div className="w-7 h-7 rounded-lg bg-white/10 border border-white/15 flex items-center justify-center text-white shadow-xs flex-shrink-0">
              <Home className="w-4 h-4 stroke-[2.25]" />
            </div>
            <span
              className={cn(
                "font-heading font-bold text-[17px] tracking-[-0.02em] text-white",
                compact ? "hidden" : "hidden xl:inline"
              )}
            >
              EstateOS
            </span>
          </Link>
        </div>

        {/* Quick Search Bar (matching reference design) */}
        <div className={cn("px-2.5 pt-2.5 pb-1", compact ? "hidden" : "hidden xl:block")}>
          <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-[#10213B] border border-[#162B45] text-slate-400 hover:text-white hover:border-[#223f66] transition-colors cursor-pointer group">
            <div className="flex items-center gap-2">
              <Search className="w-3.5 h-3.5 text-slate-400 group-hover:text-white" />
              <span className="text-[12px]">{t("nav.search_placeholder")}</span>
            </div>
            <kbd className="text-[10px] font-mono text-slate-400 bg-white/5 border border-white/10 px-1.5 py-0.5 rounded">
              ⌘K
            </kbd>
          </div>
        </div>

        {/* Section Label: WORKSPACE */}
        <div className={cn("px-3 pt-3 pb-1", compact ? "hidden" : "hidden xl:block")}>
          <span className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
            {t("nav.workspace")}
          </span>
        </div>

        {/* Main Navigation Items */}
        <nav className={cn("space-y-1", compact ? "p-2" : "p-2 xl:p-2.5")}>
          {navigationItems.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.label}
                href={item.href}
                title={item.label}
                className={cn(
                  "flex items-center min-h-[38px] rounded-xl text-[13.5px] transition-all relative group",
                  compact
                    ? "justify-center px-2"
                    : "justify-center xl:justify-between px-2 xl:px-3",
                  isActive
                    ? "bg-white/10 border border-white/10 text-white font-medium shadow-xs"
                    : "text-zinc-400 hover:text-white hover:bg-white/5 font-medium border border-transparent"
                )}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="relative">
                    <Icon
                      className={cn(
                        "w-4 h-4 flex-shrink-0 transition-colors",
                        isActive ? "text-white" : "text-zinc-400 group-hover:text-white"
                      )}
                      strokeWidth={isActive ? 2 : 1.75}
                    />
                    {/* Compact badge dot for icon nav */}
                    {item.badge !== undefined && (
                      <span
                        className={cn(
                          "absolute -top-1 -right-1.5 w-2 h-2 rounded-full bg-[var(--accent)] ring-2 ring-[#0A1B2F]",
                          compact ? "block" : "xl:hidden"
                        )}
                      />
                    )}
                  </div>
                  <span className={cn("truncate", compact ? "hidden" : "hidden xl:inline")}>
                    {item.label}
                  </span>
                </div>

                {/* Badge matching the design screenshot */}
                {item.badge !== undefined && (
                  <span
                    className={cn(
                      "text-[11px] tabular-nums leading-none",
                      compact ? "hidden" : "hidden xl:inline-flex",
                      isActive
                        ? "text-slate-200 font-medium"
                        : "text-slate-400 group-hover:text-slate-300"
                    )}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: Knowledge Base, Connections & User Profile */}
      <div className="border-t border-[#162B45]">
        <div className={cn("space-y-1", compact ? "p-2" : "p-2 xl:p-2.5")}>
          {/* Knowledge Base */}
          {canAccess("reports") && (
            <Link
              href="/reports"
              title={t("nav.knowledge_base") || "Knowledge Base"}
              className={cn(
                "w-full flex items-center min-h-[38px] rounded-xl text-[13.5px] transition-colors text-slate-400 hover:text-white hover:bg-white/5 font-medium gap-2.5 border border-transparent",
                compact ? "justify-center px-2" : "justify-center xl:justify-start px-2 xl:px-3"
              )}
            >
              <BookOpen className="w-4 h-4 flex-shrink-0 text-slate-400" strokeWidth={1.75} />
              <span className={cn("truncate", compact ? "hidden" : "hidden xl:inline")}>
                {t("nav.knowledge_base") || "Knowledge Base"}
              </span>
            </Link>
          )}

          {/* Connections Trigger Button */}
          <button
            type="button"
            onClick={() => setIsConnectionsOpen(true)}
            title={t("nav.connections")}
            className={cn(
              "w-full flex items-center min-h-[38px] rounded-xl text-[13.5px] transition-colors relative group cursor-pointer text-slate-400 hover:text-white hover:bg-white/5 font-medium border border-transparent",
              compact ? "justify-center px-2" : "justify-center xl:justify-between px-2 xl:px-3"
            )}
          >
            <div className="flex items-center gap-2.5 min-w-0 relative">
              <LayoutGrid
                className="w-4 h-4 flex-shrink-0 text-slate-400 group-hover:text-white transition-colors"
                strokeWidth={1.75}
              />
              {compact && (
                <span className="absolute -top-0.5 -right-1 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-[#0A1B2F]" />
              )}
              <span className={cn("truncate", compact ? "hidden" : "hidden xl:inline")}>
                {t("nav.connections")}
              </span>
            </div>
            <span
              className={cn(
                "items-center gap-1.5 text-[10.5px] font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20",
                compact ? "hidden" : "hidden xl:inline-flex"
              )}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              {t("nav.live")}
            </span>
          </button>
        </div>

        {/* User Profile & Logout Popover */}
        <div className="relative border-t border-[#162B45]">
          {isUserMenuOpen && (
            <div
              className={cn(
                "absolute bottom-full mb-2 p-2 rounded-xl bg-[#0E2138] border border-[#162B45] shadow-xl z-50 animate-in fade-in slide-in-from-bottom-2 duration-150",
                compact ? "left-2 w-[220px]" : "left-2 right-2"
              )}
            >
              <div className="px-2 py-1.5 border-b border-[#162B45] mb-1">
                <span className="text-xs font-semibold text-white block truncate">{displayName}</span>
                <span className="text-[11px] text-[#94a3b8] block truncate font-mono">{displayEmail}</span>
                <span className="inline-block mt-1 px-1.5 py-0.2 rounded text-[9.5px] uppercase font-bold tracking-wider bg-[#1a73e8]/20 text-[#60a5fa] border border-[#1a73e8]/30">
                  {user?.role || "Owner"}
                </span>
              </div>
              {user?.isAdmin && (
                <div className="py-1 border-b border-[#222830] mb-1">
                  <Link
                    href="/admin"
                    onClick={() => setIsUserMenuOpen(false)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs font-medium text-zinc-300 hover:text-white hover:bg-white/5 transition-colors"
                  >
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>Team & access</span>
                  </Link>
                  <Link
                    href="/admin?new=1"
                    onClick={() => setIsUserMenuOpen(false)}
                    className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs font-medium text-zinc-300 hover:text-white hover:bg-white/5 transition-colors"
                  >
                    <UserPlus className="w-3.5 h-3.5" />
                    <span>Add a profile</span>
                  </Link>
                </div>
              )}
              <button
                type="button"
                onClick={() => {
                  setIsUserMenuOpen(false);
                  logout();
                }}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs font-medium text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 transition-colors cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>{t("nav.sign_out")}</span>
              </button>
            </div>
          )}

          <div
            onClick={() => setIsUserMenuOpen((prev) => !prev)}
            className={cn(
              "flex items-center gap-2.5 bg-white/[0.02] hover:bg-white/[0.06] transition-colors cursor-pointer select-none",
              compact ? "p-2.5 justify-center" : "p-2.5 xl:p-3 justify-between"
            )}
            title={user?.isAdmin ? "Profile, team & access, sign out" : "Profile & sign out"}
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-7 h-7 xl:w-8 xl:h-8 rounded-full bg-[#162B45] border border-white/10 flex items-center justify-center text-[11px] font-bold text-slate-200 flex-shrink-0">
                {userInitials}
              </div>
              <div className={cn("flex-col min-w-0", compact ? "hidden" : "hidden xl:flex")}>
                <span className="text-[13px] font-semibold text-white truncate leading-tight">
                  {displayName}
                </span>
                <span className="text-[11px] text-slate-400 truncate leading-tight mt-0.5">
                  {displayEmail}
                </span>
              </div>
            </div>
            <ChevronDown
              className={cn(
                "w-3.5 h-3.5 text-slate-400 flex-shrink-0 transition-transform",
                compact ? "hidden" : "hidden xl:block",
                isUserMenuOpen && "rotate-180 text-white"
              )}
            />
          </div>
        </div>
      </div>
      <ConnectionsModal isOpen={isConnectionsOpen} onClose={() => setIsConnectionsOpen(false)} />
    </aside>
  );
}
