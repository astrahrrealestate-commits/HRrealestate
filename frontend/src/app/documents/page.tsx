"use client";

import React, { Suspense, useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { DocumentLibrarySection } from "@/components/knowledge/DocumentLibrarySection";
import { Loader2 } from "lucide-react";

export default function DocumentsPage() {
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);

  return (
    <div className="flex h-dvh bg-[var(--bg)] text-[var(--ink)] overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        <TopCommandBar pageTitle="Documents" hideSearch onAskAgent={() => setIsAskAgentOpen(true)} />
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 pb-24 md:pb-8">
          <div className="max-w-5xl mx-auto">
            <Suspense
              fallback={
                <div className="flex items-center justify-center py-12 text-xs text-[var(--ink-3)]">
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  Loading documents…
                </div>
              }
            >
              <DocumentLibrarySection />
            </Suspense>
          </div>
        </main>
      </div>
      <MobileTabBar />
      <AskEstateOSPanel isOpen={isAskAgentOpen} onClose={() => setIsAskAgentOpen(false)} />
    </div>
  );
}
