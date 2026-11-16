"use client";

import React from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { useLanguage } from "@/context/LanguageContext";

/** The page frame with one honest message in it: loading, cannot reach the server, or nothing recorded yet. */
export function PageStateShell({ title, message, alert = false }: { title: string; message: string; alert?: boolean }) {
  const { t } = useLanguage();

  return (
    <div className="h-dvh bg-[#1B1B1B] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#1B1B1B]">
        <TopCommandBar pageTitle={t(title, title)} hideSearch={true} />
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] flex items-center justify-center p-8 text-center">
            <p className="text-[14px] text-[var(--ink-2)] font-medium" role={alert ? "alert" : "status"}>
              {t(message, message)}
            </p>
          </div>
          <AskEstateOSPanel currentPageName={title} />
        </div>
      </div>
      <MobileTabBar />
    </div>
  );
}
