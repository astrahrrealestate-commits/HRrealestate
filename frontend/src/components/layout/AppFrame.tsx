"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";

/**
 * The part of the screen that stays put between pages: the left navigation is mounted once here, so moving to
 * another page swaps only the content beside it (ADR 0018). The login page has no navigation.
 */
export function AppFrame({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  if (pathname === "/login") return <>{children}</>;

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[#0A1B2F]">
      <Sidebar />
      <div className="flex-1 min-w-0 h-dvh overflow-hidden">{children}</div>
    </div>
  );
}
