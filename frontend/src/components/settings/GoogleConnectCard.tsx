"use client";

import React, { useState, useEffect } from "react";
import { Mail, Calendar, Folder, CheckCircle2, AlertCircle, RefreshCw, LogOut, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { GoogleAuthStatus, getGoogleAuthStatus, getGoogleAuthUrl, disconnectGoogleAccount } from "@/lib/api";

export function GoogleConnectCard() {
  const [status, setStatus] = useState<GoogleAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Check URL query parameters on return from Google OAuth
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("google_connected") === "success") {
        const email = params.get("email");
        setMessage({
          type: "success",
          text: email ? `Successfully connected Google account (${email})!` : "Google account connected successfully!",
        });
        // Clean URL
        window.history.replaceState({}, document.title, window.location.pathname);
      } else if (params.get("google_error")) {
        setMessage({
          type: "error",
          text: `Google connection failed: ${params.get("google_error")}`,
        });
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    }
  }, []);

  // Fetch connection status
  const refreshStatus = async () => {
    setLoading(true);
    const data = await getGoogleAuthStatus();
    setStatus(data);
    setLoading(false);
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  const handleConnect = async () => {
    setConnecting(true);
    const url = await getGoogleAuthUrl();
    if (url) {
      window.location.href = url;
    } else {
      setMessage({ type: "error", text: "Could not generate Google authorization link." });
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("Are you sure you want to disconnect this Google account? Gmail, Calendar, and Drive sync will be paused.")) {
      return;
    }
    setDisconnecting(true);
    const ok = await disconnectGoogleAccount();
    if (ok) {
      setMessage({ type: "success", text: "Google account disconnected." });
      await refreshStatus();
    } else {
      setMessage({ type: "error", text: "Failed to disconnect Google account." });
    }
    setDisconnecting(false);
  };

  return (
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
                Google Workspace & Personal Account
              </h3>
              {status?.connected && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#ECFDF5] text-[#059669] dark:bg-[#064E3B]/30 dark:text-[#34D399] border border-[#A7F3D0] dark:border-[#065F46]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#10B981] animate-pulse"></span>
                  Active & Synced
                </span>
              )}
            </div>
            <p className="text-[13px] text-[#71717A] mt-0.5">
              Connect Harjot&apos;s Google account once for unified Gmail inbox ingestion, Calendar scheduling, and Drive filing.
            </p>
          </div>
        </div>

        {/* Action Button */}
        <div>
          {loading ? (
            <div className="text-[12px] text-[#A1A1AA] flex items-center gap-1.5 py-1.5">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Checking...
            </div>
          ) : status?.connected ? (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleConnect}
                disabled={connecting}
                className="text-[12px] h-8 px-3 rounded-[8px] font-medium border-[#E4E4E7] dark:border-[#2E2E2E]"
              >
                <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${connecting ? "animate-spin" : ""}`} />
                Switch Account
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="text-[12px] h-8 px-2.5 rounded-[8px] text-[#DC2626] hover:bg-[#FEF2F2] dark:hover:bg-[#450A0A]/20 border-[#E4E4E7] dark:border-[#2E2E2E]"
                title="Disconnect Google Account"
              >
                <LogOut className="w-3.5 h-3.5" />
              </Button>
            </div>
          ) : (
            <Button
              onClick={handleConnect}
              disabled={connecting}
              size="sm"
              className="text-[13px] h-9 px-4 rounded-[8px] font-medium bg-[#18181B] text-[#FFFFFF] hover:bg-[#27272A] dark:bg-[#F4F4F5] dark:text-[#18181B] shadow-sm"
            >
              {connecting ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                  Connecting...
                </>
              ) : (
                <>Connect with Google</>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Toast Alert */}
      {message && (
        <div
          className={`mt-4 p-3 rounded-[10px] text-[13px] flex items-center justify-between gap-2.5 ${
            message.type === "success"
              ? "bg-[#F0FDF4] text-[#166534] border border-[#BBF7D0]"
              : "bg-[#FEF2F2] text-[#991B1B] border border-[#FECACA]"
          }`}
        >
          <div className="flex items-center gap-2">
            {message.type === "success" ? (
              <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-[#16A34A]" />
            ) : (
              <AlertCircle className="w-4 h-4 flex-shrink-0 text-[#DC2626]" />
            )}
            <span>{message.text}</span>
          </div>
          <button
            onClick={() => setMessage(null)}
            className="text-[11px] font-semibold underline hover:opacity-80"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Connected Account Details */}
      {status?.connected && (
        <div className="mt-5 pt-4 border-t border-[#F4F4F5] dark:border-[#1F1F1F]">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              {status.picture ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={status.picture}
                  alt={status.name || "Owner"}
                  className="w-9 h-9 rounded-full border border-[#E5E5E5] dark:border-[#2E2E2E]"
                />
              ) : (
                <div className="w-9 h-9 rounded-full bg-[#F25C05]/10 text-[#F25C05] font-semibold text-[13px] flex items-center justify-center border border-[#F25C05]/20">
                  {status.name ? status.name.charAt(0).toUpperCase() : "H"}
                </div>
              )}
              <div>
                <p className="text-[13px] font-medium text-[#18181B] dark:text-[#F4F4F5]">
                  {status.name || "Harjot Singh"}
                </p>
                <p className="text-[12px] text-[#71717A]">{status.email}</p>
              </div>
            </div>
            <span className="text-[11px] text-[#A1A1AA]">Permanent Offline Token</span>
          </div>

          {/* Connected Services Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 mt-3">
            <div className="p-2.5 rounded-[10px] bg-[#FAFAFA] dark:bg-[#181818] border border-[#F4F4F5] dark:border-[#222222] flex items-center gap-2.5">
              <Mail className="w-4 h-4 text-[#EA4335]" />
              <div>
                <div className="text-[12px] font-medium text-[#27272A] dark:text-[#E4E4E7]">
                  Gmail Sync & Drafts
                </div>
                <div className="text-[10px] text-[#71717A]">Auto-triage inbound mail</div>
              </div>
            </div>
            <div className="p-2.5 rounded-[10px] bg-[#FAFAFA] dark:bg-[#181818] border border-[#F4F4F5] dark:border-[#222222] flex items-center gap-2.5">
              <Calendar className="w-4 h-4 text-[#4285F4]" />
              <div>
                <div className="text-[12px] font-medium text-[#27272A] dark:text-[#E4E4E7]">
                  Google Calendar
                </div>
                <div className="text-[10px] text-[#71717A]">Contractor & tenant visits</div>
              </div>
            </div>
            <div className="p-2.5 rounded-[10px] bg-[#FAFAFA] dark:bg-[#181818] border border-[#F4F4F5] dark:border-[#222222] flex items-center gap-2.5">
              <Folder className="w-4 h-4 text-[#FBBC05]" />
              <div>
                <div className="text-[12px] font-medium text-[#27272A] dark:text-[#E4E4E7]">
                  Google Drive
                </div>
                <div className="text-[10px] text-[#71717A]">Lease & invoice filing</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
