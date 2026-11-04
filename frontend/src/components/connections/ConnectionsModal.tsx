"use client";

import React, { useState } from "react";
import {
  LayoutGrid,
  X,
  Check,
  MoreVertical,
  Loader2,
  LogOut,
} from "lucide-react";

interface ConnectionsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConnectionsModal({ isOpen, onClose }: ConnectionsModalProps) {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [waLoading, setWaLoading] = useState<boolean>(false);
  const [isWaConnected, setIsWaConnected] = useState<boolean>(false);

  const handleConnectWhatsApp = () => {
    setWaLoading(true);
    setTimeout(() => {
      setWaLoading(false);
      setIsWaConnected(true);
    }, 600);
  };

  const handleDisconnectWhatsApp = () => {
    setIsWaConnected(false);
    setActiveMenu(null);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-[530px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-xl overflow-hidden z-10 transition-all select-none p-6">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 shrink-0 mt-0.5">
              <LayoutGrid className="w-4 h-4 stroke-[2]" />
            </div>
            <div>
              <h2 className="font-semibold text-[17px] text-zinc-900 dark:text-zinc-100 leading-tight">
                Connections
              </h2>
              <p className="text-[12px] text-zinc-500 dark:text-zinc-400 mt-1">
                Active integrations powering EstateOS Super Agent automated triage
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Connections List */}
        <div className="mt-5 space-y-0 divide-y divide-zinc-100 dark:divide-zinc-800/80">
          {/* 1. Gmail - Connected */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              {/* Gmail Icon */}
              <div className="w-10 h-10 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-2xs flex items-center justify-center shrink-0">
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path
                    fill="#EA4335"
                    d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"
                  />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">
                  Gmail
                </div>
                <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">
                  Tenant inquiries, service notices & statements
                </div>
                <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">
                  arthur.estateos@gmail.com · Synced 2m ago
                </div>
              </div>
            </div>

            {/* Status / Action */}
            <div className="relative shrink-0 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60">
                <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                Connected
              </span>
              <button
                onClick={() => setActiveMenu(activeMenu === "gmail" ? null : "gmail")}
                className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
              {activeMenu === "gmail" && (
                <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                  <button
                    onClick={() => setActiveMenu(null)}
                    className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 flex items-center gap-2 cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    Disconnect
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 2. WhatsApp Business - Not Connected */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-2xs flex items-center justify-center shrink-0">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 21a9 9 0 1 0-7.5-4L3 21l4.2-1.4A8.96 8.96 0 0 0 12 21z"
                    fill="#25D366"
                    fillOpacity="0.15"
                    stroke="#25D366"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M9.5 9.5c.3-.6.6-.6.9-.6h.7c.2 0 .4.1.5.4.3.7.8 1.9.9 2 .1.2.1.3 0 .5l-.4.5c-.1.2-.3.3-.1.6.4.7 1.1 1.4 1.8 1.8.3.2.4.1.6-.1l.5-.4c.2-.1.3-.1.5 0 .1.1 1.3.6 2 .9.3.1.4.3.4.5v.7c0 .3-.1.6-.6.9-.7.4-1.8.5-3.3-.2-2.3-1-4-3-4.8-4.3-.8-1.5-.7-2.6-.3-3.3z"
                    fill="#25D366"
                  />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">
                  WhatsApp Business
                </div>
                <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">
                  Instant tenant dispatch & messaging
                </div>
                <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">
                  {isWaConnected ? "+31 6 3648 40587 (Desk) · Synced live" : "+31 6 3648 40587 · Not connected"}
                </div>
              </div>
            </div>

            <div className="relative shrink-0 flex items-center gap-1.5">
              {isWaConnected ? (
                <>
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60">
                    <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                    Connected
                  </span>
                  <button
                    onClick={() => setActiveMenu(activeMenu === "wa" ? null : "wa")}
                    className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                  {activeMenu === "wa" && (
                    <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                      <button
                        onClick={handleDisconnectWhatsApp}
                        className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 flex items-center gap-2 cursor-pointer"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        Disconnect
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <button
                  onClick={handleConnectWhatsApp}
                  disabled={waLoading}
                  className="px-4 py-1.5 rounded-lg text-[12.5px] font-medium bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-white transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs"
                >
                  {waLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-white dark:text-zinc-900" />
                  ) : (
                    "Connect"
                  )}
                </button>
              )}
            </div>
          </div>

          {/* 3. Google Drive - Connected */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-2xs flex items-center justify-center shrink-0">
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M14.7 3.5H9.3L2 16.2l2.7 4.7 7.4-12.8 2.6-4.6z" />
                  <path fill="#FBBC05" d="M22 16.2L14.7 3.5h-5.4l7.3 12.7H22z" />
                  <path fill="#34A853" d="M19.3 20.9H4.7L2 16.2h14.6l2.7 4.7z" />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">
                  Google Drive
                </div>
                <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">
                  Tenancy leases, compliance documents & inspection photos
                </div>
                <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">
                  arthur.estateos@gmail.com · Document storage active
                </div>
              </div>
            </div>

            <div className="relative shrink-0 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60">
                <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                Connected
              </span>
              <button
                onClick={() => setActiveMenu(activeMenu === "drive" ? null : "drive")}
                className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
              {activeMenu === "drive" && (
                <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                  <button
                    onClick={() => setActiveMenu(null)}
                    className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 flex items-center gap-2 cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    Disconnect
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 4. Google Calendar - Connected */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-2xs flex items-center justify-center shrink-0">
                <div className="w-5 h-5 rounded-md border-2 border-blue-600 flex flex-col overflow-hidden">
                  <div className="h-1.5 bg-blue-600 w-full" />
                  <div className="flex-1 flex items-center justify-center text-[9px] font-bold text-blue-600 leading-none">
                    31
                  </div>
                </div>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">
                  Google Calendar
                </div>
                <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">
                  Scheduled viewings, maintenance callouts & lease renewals
                </div>
                <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">
                  arthur.pendelton@estateos.internal · Synced 5m ago
                </div>
              </div>
            </div>

            <div className="relative shrink-0 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60">
                <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                Connected
              </span>
              <button
                onClick={() => setActiveMenu(activeMenu === "cal" ? null : "cal")}
                className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
              {activeMenu === "cal" && (
                <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                  <button
                    onClick={() => setActiveMenu(null)}
                    className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 flex items-center gap-2 cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    Disconnect
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 5. BRIXX - Connected */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-sky-500 shadow-2xs flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.25" />
                  <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.25" />
                  <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.25" />
                  <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" fill="currentColor" fillOpacity="0.25" />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">
                  BRIXX
                </div>
                <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">
                  Financial modeling, cash flow ledger & property forecasting
                </div>
                <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">
                  Financial modeling ledger · Synced live
                </div>
              </div>
            </div>

            <div className="relative shrink-0 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60">
                <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                Connected
              </span>
              <button
                onClick={() => setActiveMenu(activeMenu === "brixx" ? null : "brixx")}
                className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
              >
                <MoreVertical className="w-4 h-4" />
              </button>
              {activeMenu === "brixx" && (
                <div className="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                  <button
                    onClick={() => setActiveMenu(null)}
                    className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20 flex items-center gap-2 cursor-pointer"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    Disconnect
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 pt-2 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-[12.5px] font-medium bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-white transition-colors cursor-pointer shadow-2xs"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
