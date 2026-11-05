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
  LayoutGrid,
  BookOpen,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { needsYouCount, ThreadCountTarget } from "@/lib/selectors";
import { getInboxThreads } from "@/lib/api";

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

  const navigationItems: NavItem[] = [
    {
      label: "Dashboard",
      href: "/",
      icon: Home,
      badge: effectiveCount > 0 ? `(${effectiveCount} Today)` : undefined,
    },
    {
      label: "Messages",
      href: "/inbox",
      icon: Inbox,
      badge: effectiveCount > 0 ? `(${effectiveCount})` : undefined,
    },
    { label: "Properties", href: "/properties", icon: Building2 },
    { label: "Tenants", href: "/tenants", icon: Users },
    { label: "Contacts", href: "/contacts", icon: Contact },
    { label: "Maintenance", href: "/maintenance", icon: Wrench },
  ];

  return (
    <aside className="hidden md:flex flex-col justify-between select-none h-dvh sticky top-0 md:w-[72px] xl:w-[240px] flex-shrink-0 border-r border-[#27272a] bg-[#1B1B1B] transition-all z-20">
      {/* Top Header & Navigation */}
      <div className="flex flex-col">
        {/* Brand Logo Header (h-14 aligned with TopCommandBar) */}
        <div className="h-[48px] px-4 xl:px-4 flex items-center justify-between border-b border-[#27272a]">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-7 h-7 rounded-lg bg-white/10 border border-white/15 flex items-center justify-center text-white shadow-xs flex-shrink-0">
              <Home className="w-4 h-4 stroke-[2.25]" />
            </div>
            <span className="hidden xl:inline font-heading font-bold text-[17px] tracking-[-0.02em] text-white">
              EstateOS
            </span>
          </Link>
        </div>

        {/* Section Label: WORKSPACE */}
        <div className="px-3 pt-3 pb-1 hidden xl:block">
          <span className="text-[10px] font-bold tracking-wider text-zinc-500 uppercase">
            WORKSPACE
          </span>
        </div>

        {/* Main Navigation Items */}
        <nav className="p-2 xl:p-2.5 space-y-1">
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
                  "justify-center xl:justify-between px-2 xl:px-3",
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
                    {/* Compact badge dot for icon nav (md only) */}
                    {item.badge !== undefined && (
                      <span className="xl:hidden absolute -top-1 -right-1.5 w-2 h-2 rounded-full bg-[var(--accent)] ring-2 ring-[#1B1B1B]" />
                    )}
                  </div>
                  <span className="hidden xl:inline truncate">{item.label}</span>
                </div>

                {/* Badge matching the design screenshot */}
                {item.badge !== undefined && (
                  <span
                    className={cn(
                      "hidden xl:inline-flex text-[11px] tabular-nums leading-none",
                      isActive
                        ? "text-zinc-300 font-medium"
                        : "text-zinc-500 group-hover:text-zinc-400"
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
      <div className="border-t border-white/5">
        <div className="p-2 xl:p-2.5 space-y-1">
          {/* Knowledge Base */}
          <Link
            href="/reports"
            title="Knowledge Base"
            className="w-full flex items-center min-h-[38px] rounded-xl text-[13.5px] transition-colors justify-center xl:justify-start px-2 xl:px-3 text-zinc-400 hover:text-white hover:bg-white/5 font-medium gap-2.5 border border-transparent"
          >
            <BookOpen className="w-4 h-4 flex-shrink-0 text-zinc-400" strokeWidth={1.75} />
            <span className="hidden xl:inline truncate">Knowledge Base</span>
          </Link>

          {/* Connections Trigger Button */}
          <button
            type="button"
            onClick={() => setIsConnectionsOpen(true)}
            title="Connections & Integrations"
            className="w-full flex items-center min-h-[38px] rounded-xl text-[13.5px] transition-colors relative group justify-center xl:justify-between px-2 xl:px-3 cursor-pointer text-zinc-400 hover:text-white hover:bg-white/5 font-medium border border-transparent"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <LayoutGrid
                className="w-4 h-4 flex-shrink-0 text-zinc-400 group-hover:text-white transition-colors"
                strokeWidth={1.75}
              />
              <span className="hidden xl:inline truncate">Connections</span>
            </div>
            <span className="hidden xl:inline-flex items-center gap-1.5 text-[10.5px] font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Live
            </span>
          </button>
        </div>

        {/* User Profile */}
        <div className="p-2.5 xl:p-3 border-t border-white/5 flex items-center justify-between gap-2.5 bg-white/[0.02]">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-7 h-7 xl:w-8 xl:h-8 rounded-full bg-zinc-800 border border-white/10 flex items-center justify-center text-[11px] font-bold text-zinc-200 flex-shrink-0">
              HS
            </div>
            <div className="hidden xl:flex flex-col min-w-0">
              <span className="text-[13px] font-semibold text-white truncate leading-tight">
                Harjot Singh
              </span>
              <span className="text-[11px] text-zinc-400 truncate leading-tight mt-0.5">
                harjot@estateos.internal
              </span>
            </div>
          </div>
          <ChevronDown className="hidden xl:block w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />
        </div>
      </div>
      <ConnectionsModal isOpen={isConnectionsOpen} onClose={() => setIsConnectionsOpen(false)} />
    </aside>
  );
}
