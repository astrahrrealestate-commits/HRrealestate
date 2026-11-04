"use client";

import React, { useState, useEffect } from "react";
import {
  LayoutGrid,
  X,
  Check,
  MoreVertical,
  Loader2,
  RefreshCw,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getGoogleAuthStatus,
  getGoogleAuthUrl,
  disconnectGoogleAccount,
  GoogleAuthStatus,
} from "@/lib/api";

interface ConnectionsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function ConnectionsModal({ isOpen, onClose }: ConnectionsModalProps) {
  const [googleStatus, setGoogleStatus] = useState<GoogleAuthStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);

  const fetchStatus = async () => {
    try {
      setLoading(true);
      const status = await getGoogleAuthStatus();
      setGoogleStatus(status);
    } catch (err) {
      console.warn("Failed to fetch Google auth status in modal:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchStatus();
    }
  }, [isOpen]);

  const handleConnectGoogle = async () => {
    try {
      setActionLoading(true);
      const authUrl = await getGoogleAuthUrl();
      if (authUrl) {
        window.location.href = authUrl;
      }
    } catch (err) {
      console.error("Failed to initiate Google OAuth:", err);
      setActionLoading(false);
    }
  };

  const handleDisconnectGoogle = async () => {
    try {
      setActionLoading(true);
      const success = await disconnectGoogleAccount();
      if (success) {
        await fetchStatus();
      }
    } catch (err) {
      console.error("Failed to disconnect Google:", err);
    } finally {
      setActionLoading(false);
      setActiveMenu(null);
    }
  };

  if (!isOpen) return null;

  const isGoogleConnected = Boolean(googleStatus?.connected);
  const googleEmail = googleStatus?.email || "";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
        onClick={onClose}
      />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-[560px] max-h-[92vh] flex flex-col bg-[var(--pane)] border border-[var(--line)] rounded-2xl shadow-2xl overflow-hidden z-10 transition-all select-none">
        {/* Header */}
        <div className="px-6 pt-5 pb-4 flex items-start justify-between border-b border-[var(--line)]/50 shrink-0">
          <div className="flex items-start gap-3">
            <div className="w-9 h-9 rounded-xl bg-[var(--selected)] border border-[var(--line)] flex items-center justify-center text-[var(--ink)] shrink-0 mt-0.5">
              <LayoutGrid className="w-5 h-5 stroke-[2]" />
            </div>
            <div>
              <h2 className="font-heading font-bold text-[18px] text-[var(--ink)] leading-tight">
                Connections
              </h2>
              <p className="text-[12.5px] text-[var(--ink-3)] mt-0.5">
                Active integrations powering EstateOS Super Agent automated triage
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={fetchStatus}
              title="Refresh status"
              disabled={loading}
              className="p-1.5 rounded-lg text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={cn("w-4 h-4", loading && "animate-spin")} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Connections List */}
        <div className="px-6 py-1 divide-y divide-[var(--line)] overflow-y-auto flex-1">
          {/* 1. Mail (Gmail) */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              {/* Gmail Icon */}
              <div className="w-10 h-10 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M3 6.5A2.5 2.5 0 0 1 5.5 4h13A2.5 2.5 0 0 1 21 6.5v11a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5v-11z"
                    fill="#EA4335"
                    fillOpacity="0.1"
                  />
                  <path
                    d="M4 6l8 5.5L20 6"
                    stroke="#EA4335"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <rect
                    x="3.5"
                    y="5"
                    width="17"
                    height="14"
                    rx="2"
                    stroke="#EA4335"
                    strokeWidth="1.5"
                  />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[14px] text-[var(--ink)] leading-snug">
                  Gmail
                </div>
                <div className="text-[12px] text-[var(--ink-3)] truncate">
                  Tenant inquiries, service notices & statements
                </div>
                {loading ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-3)] truncate mt-0.5">
                    Checking connection...
                  </div>
                ) : isGoogleConnected ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-2)] truncate mt-0.5">
                    {googleEmail} · Synced live
                  </div>
                ) : (
                  <div className="text-[11.5px] text-amber-600 dark:text-amber-400 font-medium truncate mt-0.5">
                    Note: No mailbox connected. Connect Google account to enable triage
                  </div>
                )}
              </div>
            </div>

            {/* Status / Action */}
            <div className="relative shrink-0 flex items-center gap-1.5">
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--ink-3)]" />
              ) : isGoogleConnected ? (
                <>
                  <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-[var(--ink-2)] bg-[var(--selected)]/70 border border-[var(--line)]">
                    <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                    Connected
                  </span>
                  <button
                    onClick={() => setActiveMenu(activeMenu === "gmail" ? null : "gmail")}
                    className="p-1.5 rounded-md text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
                  >
                    <MoreVertical className="w-4 h-4" />
                  </button>
                  {activeMenu === "gmail" && (
                    <div className="absolute right-0 top-full mt-1 w-36 bg-[var(--pane)] border border-[var(--line)] rounded-lg shadow-lg py-1 z-20">
                      <button
                        onClick={handleDisconnectGoogle}
                        disabled={actionLoading}
                        className="w-full px-3 py-1.5 text-left text-[12px] font-medium text-red-600 hover:bg-red-500/10 flex items-center gap-2 cursor-pointer"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        Disconnect
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <button
                  onClick={handleConnectGoogle}
                  disabled={actionLoading}
                  className="px-3.5 py-1.5 rounded-lg text-[12.5px] font-semibold bg-[var(--ink)] text-[var(--background)] hover:opacity-90 transition-opacity cursor-pointer flex items-center gap-1.5"
                >
                  {actionLoading ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    "Connect"
                  )}
                </button>
              )}
            </div>
          </div>

          {/* 2. WhatsApp Business */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center shrink-0">
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
                <div className="font-semibold text-[14px] text-[var(--ink)] leading-snug">
                  WhatsApp Business
                </div>
                <div className="text-[12px] text-[var(--ink-3)] truncate">
                  Instant tenant dispatch & messaging
                </div>
                <div className="text-[11.5px] font-mono text-[var(--ink-2)] truncate mt-0.5">
                  +31 6 3648 40587 (Desk) · Synced live
                </div>
              </div>
            </div>

            <div className="shrink-0">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-[var(--ink-2)] bg-[var(--selected)]/70 border border-[var(--line)]">
                <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                Connected
              </span>
            </div>
          </div>

          {/* 3. Google Drive */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              {/* Google Drive Icon */}
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M14.7 3.5H9.3L2 16.2l2.7 4.7 7.4-12.8 2.6-4.6z" />
                  <path fill="#FBBC05" d="M22 16.2L14.7 3.5h-5.4l7.3 12.7H22z" />
                  <path fill="#34A853" d="M19.3 20.9H4.7L2 16.2h14.6l2.7 4.7z" />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[14px] text-[var(--ink)] leading-snug">
                  Google Drive
                </div>
                <div className="text-[12px] text-[var(--ink-3)] truncate">
                  Tenancy leases, compliance documents & inspection photos
                </div>
                {loading ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-3)] truncate mt-0.5">
                    Checking connection...
                  </div>
                ) : isGoogleConnected ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-2)] truncate mt-0.5">
                    {googleEmail} · Document storage active
                  </div>
                ) : (
                  <div className="text-[11.5px] text-[var(--ink-3)] truncate mt-0.5">
                    Note: Automated lease filing & media vault
                  </div>
                )}
              </div>
            </div>

            <div className="shrink-0">
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--ink-3)]" />
              ) : isGoogleConnected ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-[var(--ink-2)] bg-[var(--selected)]/70 border border-[var(--line)]">
                  <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                  Connected
                </span>
              ) : (
                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20">
                  Coming Soon
                </span>
              )}
            </div>
          </div>

          {/* 4. Google Calendar */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center shrink-0">
                <div className="w-5 h-5 rounded-md border-2 border-blue-600 dark:border-blue-400 flex flex-col overflow-hidden">
                  <div className="h-1.5 bg-blue-600 dark:bg-blue-400 w-full" />
                  <div className="flex-1 flex items-center justify-center text-[9px] font-bold text-blue-600 dark:text-blue-400 leading-none">
                    31
                  </div>
                </div>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[14px] text-[var(--ink)] leading-snug">
                  Google Calendar
                </div>
                <div className="text-[12px] text-[var(--ink-3)] truncate">
                  Scheduled viewings, maintenance callouts & lease renewals
                </div>
                {loading ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-3)] truncate mt-0.5">
                    Checking connection...
                  </div>
                ) : isGoogleConnected ? (
                  <div className="text-[11.5px] font-mono text-[var(--ink-2)] truncate mt-0.5">
                    {googleEmail} · Calendar sync active
                  </div>
                ) : (
                  <div className="text-[11.5px] text-[var(--ink-3)] truncate mt-0.5">
                    Note: Automated viewing scheduling & dispatch
                  </div>
                )}
              </div>
            </div>

            <div className="shrink-0">
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin text-[var(--ink-3)]" />
              ) : isGoogleConnected ? (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-medium text-[var(--ink-2)] bg-[var(--selected)]/70 border border-[var(--line)]">
                  <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
                  Connected
                </span>
              ) : (
                <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20">
                  Coming Soon
                </span>
              )}
            </div>
          </div>

          {/* 5. BRIXX */}
          <div className="py-3.5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3.5 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center shrink-0">
                <svg className="w-5 h-5 text-sky-600 dark:text-sky-400" viewBox="0 0 24 24" fill="none">
                  <rect
                    x="4"
                    y="4"
                    width="7"
                    height="7"
                    rx="1.5"
                    fill="currentColor"
                    fillOpacity="0.2"
                    stroke="currentColor"
                    strokeWidth="1.7"
                  />
                  <rect
                    x="13"
                    y="4"
                    width="7"
                    height="7"
                    rx="1.5"
                    fill="currentColor"
                    fillOpacity="0.2"
                    stroke="currentColor"
                    strokeWidth="1.7"
                  />
                  <rect
                    x="4"
                    y="13"
                    width="7"
                    height="7"
                    rx="1.5"
                    fill="currentColor"
                    fillOpacity="0.2"
                    stroke="currentColor"
                    strokeWidth="1.7"
                  />
                  <rect
                    x="13"
                    y="13"
                    width="7"
                    height="7"
                    rx="1.5"
                    fill="currentColor"
                    fillOpacity="0.2"
                    stroke="currentColor"
                    strokeWidth="1.7"
                  />
                </svg>
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-[14px] text-[var(--ink)] leading-snug">
                  BRIXX
                </div>
                <div className="text-[12px] text-[var(--ink-3)] truncate">
                  Financial modeling, cash flow ledger & property forecasting
                </div>
                <div className="text-[11.5px] text-[var(--ink-3)] truncate mt-0.5">
                  Note: Portfolio cash flow modeling & multi-year forecasting ledger
                </div>
              </div>
            </div>

            <div className="shrink-0">
              <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[11.5px] font-semibold text-amber-600 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20">
                Coming Soon
              </span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3.5 bg-[var(--selected)]/40 border-t border-[var(--line)] flex justify-end shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2 rounded-lg text-[13px] font-semibold bg-[var(--ink)] text-[var(--background)] hover:opacity-90 transition-opacity cursor-pointer"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
