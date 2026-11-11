"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Lock } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { SECTION_HOME, SectionKey, sectionForPath } from "@/lib/sections";

/**
 * Shows a page only when the signed-in profile was granted its section. The API refuses the data either way; this
 * keeps a restricted person from landing on a page that can only show errors.
 */
export function SectionGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const { user, isLoading, canAccess } = useAuth();
  const section = sectionForPath(pathname);

  if (section === null) return <>{children}</>;
  if (isLoading) {
    // The page still renders (hidden) so Next can validate the segment; showing it waits for the profile.
    return (
      <>
        <div className="p-8 text-xs text-zinc-400">Loading…</div>
        <div hidden>{children}</div>
      </>
    );
  }
  if (canAccess(section)) return <>{children}</>;

  const firstOpen = (user?.sections ?? []).find((key): key is SectionKey => key in SECTION_HOME);
  return (
    <div className="flex-1 flex items-center justify-center p-8 bg-[var(--bg)]" role="alert">
      <div className="max-w-sm text-center space-y-3">
        <Lock className="w-6 h-6 mx-auto text-[var(--ink-3)]" />
        <h1 className="font-heading font-bold text-lg text-[var(--ink)]">No access to this page</h1>
        <p className="text-[13px] text-[var(--ink-2)]">
          {section === "admin"
            ? "Only a superadmin can manage the team."
            : "Your profile was not given this section. Ask a superadmin if you need it."}
        </p>
        {firstOpen ? (
          <Link
            href={SECTION_HOME[firstOpen]}
            className="inline-block text-xs font-semibold px-3 py-1.5 rounded-md border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)]"
          >
            Go to {firstOpen === "inbox" ? "messages" : firstOpen}
          </Link>
        ) : (
          <p className="text-xs text-[var(--ink-3)]">Your profile has no sections yet.</p>
        )}
      </div>
    </div>
  );
}
