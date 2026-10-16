"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Home,
  Inbox,
  Building2,
  Users,
  Contact,
  Coins,
  Wrench,
  BarChart3,
  Settings,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { needsYouCount, ThreadCountTarget } from "@/lib/selectors";
import { MOCK_INBOX_THREADS } from "@/data/inboxMockData";

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

/**
 * Sidebar implements Sections 2.1, 5.1 & 5.6:
 * - Responsive breakpoints:
 *   - 1280px+ (xl): Full nav (232px)
 *   - 768px - 1279px (md to lg): Icon nav (72px)
 *   - <768px: Hidden (replaced by bottom tab bar)
 * - Header height h-14 to match TopCommandBar
 * - Inbox count badge (orange pill) using selectors.ts single source of truth (Section 6.4)
 * - Connected services block (hidden on icon nav, visible on xl)
 */
export function Sidebar({ pendingCount, threads }: SidebarProps) {
  const pathname = usePathname() || "/";

  // Section 6.4: Single source of truth for nav count
  const effectiveCount =
    pendingCount !== undefined
      ? pendingCount
      : needsYouCount(threads || MOCK_INBOX_THREADS);

  const navigationItems: NavItem[] = [
    { label: "Today", href: "/", icon: Home },
    {
      label: "Inbox",
      href: "/inbox",
      icon: Inbox,
      badge: effectiveCount > 0 ? effectiveCount : undefined,
    },
    { label: "Properties", href: "/properties", icon: Building2 },
    { label: "Tenants", href: "/tenants", icon: Users },
    { label: "Contacts", href: "/contacts", icon: Contact },
    { label: "Money", href: "/money", icon: Coins },
    { label: "Maintenance", href: "/maintenance", icon: Wrench },
    { label: "Reports", href: "/reports", icon: BarChart3 },
    { label: "Settings", href: "/settings", icon: Settings },
    { label: "Admin", href: "/admin", icon: ShieldCheck },
  ];

  return (
    <aside className="hidden md:flex flex-col justify-between select-none h-dvh sticky top-0 md:w-[72px] xl:w-[232px] flex-shrink-0 border-r border-[var(--line)] bg-[var(--pane)] transition-all z-20">
      {/* Top Header & Navigation */}
      <div className="flex flex-col">
        {/* Brand Logo Header (h-14 aligned with TopCommandBar) */}
        <div className="h-14 px-4 xl:px-5 flex items-center border-b border-[var(--line)] justify-center xl:justify-start">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-7 h-7 rounded-[var(--radius-ctl)] bg-[var(--accent)] flex items-center justify-center text-[#0A0A0A] shadow-xs flex-shrink-0">
              <Home className="w-4 h-4 stroke-[2.25]" />
            </div>
            <span className="hidden xl:inline font-heading font-bold text-[18px] tracking-[-0.02em] text-[var(--ink)]">
              EstateOS
            </span>
          </Link>
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
                  "flex items-center min-h-[40px] rounded-[var(--radius-ctl)] text-[14px] transition-colors relative group",
                  "justify-center xl:justify-between px-2 xl:px-3",
                  isActive
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--selected)] font-medium"
                )}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div className="relative">
                    <Icon
                      className={cn(
                        "w-4 h-4 flex-shrink-0 transition-colors",
                        isActive ? "text-white" : "text-[var(--ink-3)] group-hover:text-[var(--ink)]"
                      )}
                      strokeWidth={isActive ? 2 : 1.75}
                    />
                    {/* Compact badge dot for icon nav (md only) */}
                    {item.badge !== undefined && (
                      <span className="xl:hidden absolute -top-1 -right-1.5 w-2 h-2 rounded-full bg-[var(--accent)] ring-2 ring-[var(--pane)]" />
                    )}
                  </div>
                  <span className="hidden xl:inline truncate">{item.label}</span>
                </div>

                {/* Orange pill badge (Section 3.2: orange count pill, small) */}
                {item.badge !== undefined && (
                  <span className="hidden xl:inline-flex bg-[var(--accent)] text-[#0A0A0A] text-[11px] font-bold px-2 py-0.5 rounded-full items-center justify-center tabular-nums leading-none">
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section: Connected Services & Owner Profile */}
      <div className="border-t border-[var(--line)]">
        {/* Connected Services (shown on xl only) */}
        <div className="hidden xl:block px-4 py-3 space-y-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--ink-3)]">
            CONNECTED
          </div>

          <div className="flex items-center justify-between text-[12.5px] text-[var(--ink-2)]">
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink)]" />
              Gmail
            </span>
            <span className="text-[11px] font-mono text-[var(--ink-3)]">2m ago</span>
          </div>

          <div className="flex items-center justify-between text-[12.5px] text-[var(--ink-2)]">
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink)]" />
              WhatsApp
            </span>
            <span className="text-[11px] text-[var(--ink-3)] font-medium">live</span>
          </div>

          <div className="flex items-center justify-between text-[12.5px] text-[var(--ink-2)]">
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink)]" />
              Tenant portal
            </span>
            <span className="text-[11px] text-[var(--ink-3)] font-medium">live</span>
          </div>

          <div className="flex items-center justify-between text-[12.5px] text-[var(--ink-2)]">
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--ink)]" />
              Bank feed
            </span>
            <span className="text-[11px] font-mono text-[var(--ink-3)]">06:00</span>
          </div>
        </div>

        {/* User Profile (Harjot Singh) */}
        <div className="p-2.5 xl:p-3 border-t border-[var(--line)] flex items-center justify-center xl:justify-start gap-2.5 bg-[var(--selected)]/40">
          <div className="w-7 h-7 xl:w-8 xl:h-8 rounded-full bg-[var(--selected)] border border-[var(--line)] flex items-center justify-center text-[12px] font-bold text-[var(--ink)] flex-shrink-0">
            HS
          </div>
          <div className="hidden xl:flex flex-col min-w-0">
            <span className="text-[13px] font-semibold text-[var(--ink)] truncate leading-tight">
              Harjot Singh
            </span>
            <span className="text-[11px] text-[var(--ink-3)] truncate leading-tight mt-0.5">
              H R Real Estate B.V.
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
