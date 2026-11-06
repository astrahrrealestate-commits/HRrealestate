"use client";

import React, { useState, useEffect } from "react";
import { RefreshCw, ExternalLink, LayoutGrid } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { GoogleAuthStatus, getGoogleAuthStatus } from "@/lib/api";
import { ConnectionsModal } from "@/components/connections/ConnectionsModal";

export function GoogleConnectCard() {
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Fetch connection status
  const refreshStatus = async () => {
    setLoading(true);
    const data = await getGoogleAuthStatus();
    setStatus(data);
    setLoading(false);
  };

  useEffect(() => {
    refreshStatus();
  }, [isModalOpen]);

  return (
    <>
      <div className="bg-[#FFFFFF] dark:bg-[#121212] border border-[#E5E5E5] dark:border-[#262626] rounded-[16px] p-6 shadow-sm">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3.5">
            <div className="w-11 h-11 rounded-[12px] bg-[#F4F4F5] dark:bg-[#1E1E1E] border border-[#E4E4E7] dark:border-[#2E2E2E] flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-[15px] font-semibold text-[#18181B] dark:text-[#F4F4F5]">
                  Google Workspace & External Channels
                </h3>
                {status?.connected && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#ECFDF5] text-[#059669] dark:bg-[#064E3B]/30 dark:text-[#34D399] border border-[#A7F3D0] dark:border-[#065F46]">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse"></span>
                    Active & Synced ({status.email})
                  </span>
                )}
              </div>
              <p className="text-[13px] text-[#71717A] mt-0.5">
                Manage unified integrations for Gmail, Google Calendar, Google Drive, and WhatsApp.
              </p>
            </div>
          </div>

          {/* Action Button */}
          <div>
            <Button
              onClick={() => setIsModalOpen(true)}
              size="sm"
              className="text-[13px] h-9 px-4 rounded-[8px] font-medium bg-[#18181B] text-[#FFFFFF] hover:bg-[#27272A] dark:bg-[#F4F4F5] dark:text-[#18181B] shadow-sm flex items-center gap-1.5"
            >
              <LayoutGrid className="w-3.5 h-3.5" />
              Manage in Connections
            </Button>
          </div>
        </div>

        {/* Feature status strip */}
        <div className="mt-5 pt-4 border-t border-[#F4F4F5] dark:border-[#1F1F1F] grid grid-cols-1 sm:grid-cols-3 gap-3 text-[12px]">
          <div className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
            <span
              className={`w-2 h-2 rounded-full ${
                status?.connected ? "bg-emerald-500" : "bg-zinc-400"
              }`}
            />
            <span>Gmail {status?.connected ? "Ingestion Active" : "Disconnected"}</span>
          </div>
          <div className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
            <span
              className={`w-2 h-2 rounded-full ${
                status?.connected ? "bg-emerald-500" : "bg-zinc-400"
              }`}
            />
            <span>Calendar {status?.connected ? "Sync Enabled" : "Disconnected"}</span>
          </div>
          <div className="flex items-center gap-2 text-zinc-600 dark:text-zinc-400">
            <span
              className={`w-2 h-2 rounded-full ${
                status?.connected ? "bg-emerald-500" : "bg-zinc-400"
              }`}
            />
            <span>Drive {status?.connected ? "Storage Active" : "Disconnected"}</span>
          </div>
        </div>
      </div>

      {/* Embedded Connections Modal */}
      <ConnectionsModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </>
  );
}
