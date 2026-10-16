"use client";

import React, { useState, useMemo, Suspense } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import { StatusText } from "@/components/ui/StatusText";
import {
  ShieldCheck,
  UserPlus,
  Users,
  Search,
  CheckCircle2,
  Lock,
  Mail,
  ChevronRight,
  Shield,
  KeyRound,
  FileCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { MOCK_ADMIN_USERS, AdminUser } from "@/data/adminMockData";
import { InvitePersonForm } from "@/components/admin/InvitePersonForm";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";

type AdminTab = "team" | "audit" | "security";

function AdminContent() {
  const router = useRouter();

  const [activeTab, setActiveTab] = useState<AdminTab>("team");
  const [users, setUsers] = useState<AdminUser[]>(MOCK_ADMIN_USERS);
  const [searchQuery, setSearchQuery] = useState("");
  const [isInviteFormOpen, setIsInviteFormOpen] = useState(false);
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);

  const filteredUsers = useMemo(() => {
    if (!searchQuery.trim()) return users;
    const q = searchQuery.toLowerCase();
    return users.filter(
      (u) =>
        u.name.toLowerCase().includes(q) ||
        u.email.toLowerCase().includes(q) ||
        u.role.toLowerCase().includes(q)
    );
  }, [users, searchQuery]);

  const handleInviteUser = (newUser: { name: string; email: string; role: string; complex: string }) => {
    const userItem: AdminUser = {
      id: `usr-${Date.now()}`,
      name: newUser.name,
      email: newUser.email,
      role: newUser.role as any,
      status: "invited",
      lastActive: "Invite sent just now",
      assignedComplexes: newUser.complex,
      twoFactorEnabled: false,
    };
    setUsers((prev) => [userItem, ...prev]);
  };

  return (
    <div className="min-h-dvh bg-[var(--bg)] flex font-sans antialiased text-[var(--ink)]">
      {/* 1. Left Nav (Desktop Sidebar) */}
      <Sidebar />

      {/* 2. Main Content Canvas */}
      <div className="flex-1 flex flex-col min-w-0">
        <TopCommandBar
          pageTitle="Admin"
          hideSearch={true}
          onAskAgent={() => setIsAskAgentOpen(true)}
        />

        {/* Scrollable Container */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 max-w-6xl w-full mx-auto pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12">
          
          {/* Header & Inline Stats */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--line)] pb-5">
            <div>
              <h1 className="font-heading font-bold text-[24px] sm:text-[28px] text-[var(--ink)] tracking-tight">
                Team & Governance
              </h1>
              <p className="text-xs sm:text-[13px] text-[var(--ink-2)] mt-0.5 font-mono">
                {users.length} authorized administrators · 2FA Enforced · Zero Security Exceptions
              </p>
            </div>

            {/* Invite Action (Ghost button) */}
            <div className="shrink-0">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsInviteFormOpen(true)}
                className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] gap-1.5 shadow-2xs font-semibold"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>Invite person</span>
              </Button>
            </div>
          </div>

          {/* Controls: Scrollable Tabs + Search (Section 5.6.1: Scrollable tabs, people as rows) */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-3 shadow-2xs">
            
            {/* Scrollable Tabs */}
            <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar text-xs">
              <button
                onClick={() => setActiveTab("team")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "team"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                Team ({users.length})
              </button>
              <button
                onClick={() => setActiveTab("audit")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "audit"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                Audit Log (142)
              </button>
              <button
                onClick={() => setActiveTab("security")}
                className={cn(
                  "px-3 py-1.5 rounded-md font-medium whitespace-nowrap transition-colors cursor-pointer",
                  activeTab === "security"
                    ? "bg-[var(--ink)] text-white font-semibold"
                    : "bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] border border-[var(--line)]"
                )}
              >
                Security & 2FA
              </button>
            </div>

            {/* Search */}
            <div className="relative sm:w-60">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search team member..."
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
              />
            </div>

          </div>

          {/* CONTENT: People as Rows (Section 5.6.1: People as rows, on both desktop & mobile) */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs divide-y divide-[var(--line)]">
            {filteredUsers.map((user) => (
              <div
                key={user.id}
                className="p-4 sm:px-5 sm:py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 hover:bg-[var(--selected)]/30 transition-colors"
              >
                {/* Person details */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="font-semibold text-[15px] text-[var(--ink)]">
                      {user.name}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded bg-[var(--selected)] text-[var(--ink-2)] border border-[var(--line)] font-medium">
                      {user.role}
                    </span>
                    {user.twoFactorEnabled && (
                      <span className="text-[11px] text-emerald-600 font-medium flex items-center gap-1">
                        <Lock className="w-3 h-3" />
                        <span>2FA Enabled</span>
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-[var(--ink-3)] mt-1 flex items-center gap-2 flex-wrap">
                    <span>{user.email}</span>
                    <span>·</span>
                    <span>Assigned: {user.assignedComplexes}</span>
                    <span>·</span>
                    <span>{user.lastActive}</span>
                  </div>
                </div>

                {/* Status + Actions */}
                <div className="flex items-center gap-3 shrink-0 self-end sm:self-center">
                  <StatusText status={user.status} />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => alert(`Managing permissions for ${user.name}`)}
                    className="text-xs border border-[var(--line)]"
                  >
                    Manage
                  </Button>
                </div>
              </div>
            ))}

            {filteredUsers.length === 0 && (
              <div className="text-center py-16 text-[var(--ink-3)] text-xs">
                No team members match your search.
              </div>
            )}
          </div>

          {/* Governance Notes */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] p-4 text-xs text-[var(--ink-2)] space-y-1">
            <span className="font-semibold text-[var(--ink)] block">
              GDPR & Compliance Protocol
            </span>
            <p className="leading-relaxed">
              All portfolio managers operate under role-based access control (RBAC). In accordance with Dutch data protection authority (Autoriteit Persoonsgegevens) requirements, export actions and leaseholder identity inspections are logged to the immutable audit trail.
            </p>
          </div>

        </main>

      </div>

      {/* 3. Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* 4. Full-Screen on Mobile / Dialog on Desktop Invite Person Form (Section 5.6.1) */}
      <InvitePersonForm
        isOpen={isInviteFormOpen}
        onClose={() => setIsInviteFormOpen(false)}
        onInvite={handleInviteUser}
      />

      {/* 5. Ask EstateOS Side Panel */}
      <AskEstateOSPanel
        isOpen={isAskAgentOpen}
        onClose={() => setIsAskAgentOpen(false)}
        currentPageName="Admin"
        selectedContext="Team Administration & Governance"
      />
    </div>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading Admin...</div>}>
      <AdminContent />
    </Suspense>
  );
}
