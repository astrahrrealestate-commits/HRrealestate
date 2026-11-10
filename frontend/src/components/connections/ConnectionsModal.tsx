"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import {
  LayoutGrid,
  X,
  Check,
  MoreVertical,
  Loader2,
  LogOut,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
} from "lucide-react";
import {
  GoogleAuthStatus,
  BrixxSyncStatus,
  WhatsAppSetup,
  getBrixxSyncStatus,
  getGoogleAuthStatus,
  getGoogleAuthUrl,
  getWhatsAppSetup,
  disconnectGoogleAccount,
} from "@/lib/api";
import { formatStamp } from "@/lib/clock";

interface ConnectionsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const PRIMARY_BUTTON =
  "px-4 py-1.5 rounded-lg text-[12.5px] font-medium bg-black dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-white transition-colors cursor-pointer flex items-center gap-1.5 shadow-2xs disabled:opacity-60";
const KEBAB_BUTTON =
  "p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer";
const MENU_ITEM =
  "w-full px-3 py-1.5 text-left text-[12px] font-medium flex items-center gap-2 cursor-pointer disabled:opacity-60";
const BADGE =
  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[12px] font-normal text-zinc-600 dark:text-zinc-300 bg-zinc-100/90 dark:bg-zinc-800/80 border border-zinc-200/80 dark:border-zinc-700/60";

/** One line of the list: an icon, what it is for, what state it is really in, and the action on the right. */
function ConnectionRow({
  icon,
  iconClass,
  title,
  description,
  statusLine,
  children,
}: {
  icon: React.ReactNode;
  iconClass: string;
  title: string;
  description: string;
  statusLine: string;
  children: React.ReactNode;
}) {
  return (
    <div className="py-3.5 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3.5 min-w-0">
        <div className={iconClass}>{icon}</div>
        <div className="min-w-0">
          <div className="font-semibold text-[13.5px] text-zinc-900 dark:text-zinc-100 leading-snug">{title}</div>
          <div className="text-[12px] text-zinc-500 dark:text-zinc-400 truncate">{description}</div>
          <div className="text-[11.5px] text-zinc-400 dark:text-zinc-500 truncate mt-0.5">{statusLine}</div>
        </div>
      </div>
      <div className="relative shrink-0 flex items-center gap-1.5">{children}</div>
    </div>
  );
}

export function ConnectionsModal({ isOpen, onClose }: ConnectionsModalProps) {
  const [mounted, setMounted] = useState(false);
  const [activeMenu, setActiveMenu] = useState<string | null>(null);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- portal needs the client document
    setMounted(true);
  }, []);

  // Real Google OAuth state
  const [googleStatus, setGoogleStatus] = useState<GoogleAuthStatus | null>(null);
  const [loadingGoogle, setLoadingGoogle] = useState<boolean>(true);
  const [connectingGoogle, setConnectingGoogle] = useState<boolean>(false);
  const [disconnectingGoogle, setDisconnectingGoogle] = useState<boolean>(false);

  // WhatsApp and BRIXX are read from the server; undefined = still loading, null = could not be read
  const [whatsApp, setWhatsApp] = useState<WhatsAppSetup | null | undefined>(undefined);
  const [brixx, setBrixx] = useState<BrixxSyncStatus | null | undefined>(undefined);

  const [bannerMessage, setBannerMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const fetchGoogleStatus = useCallback(async () => {
    setLoadingGoogle(true);
    try {
      setGoogleStatus(await getGoogleAuthStatus());
    } catch {
      setGoogleStatus({ connected: false, unreachable: true });
    } finally {
      setLoadingGoogle(false);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setWhatsApp(undefined);
    setBrixx(undefined);
    void fetchGoogleStatus();
    const [wa, bx] = await Promise.all([getWhatsAppSetup(), getBrixxSyncStatus()]);
    setWhatsApp(wa);
    setBrixx(bx);
  }, [fetchGoogleStatus]);

  useEffect(() => {
    if (isOpen) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- load the live statuses when the panel opens
      void fetchAll();
    }
  }, [isOpen, fetchAll]);

  // Esc closes the open menu first, then a pending confirmation, then the panel; focus starts on the close button.
  useEffect(() => {
    if (!isOpen) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    return () => opener?.focus();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (activeMenu) setActiveMenu(null);
      else if (confirmingDisconnect) setConfirmingDisconnect(false);
      else onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, activeMenu, confirmingDisconnect, onClose]);

  // Redirect parameters from the Google OAuth callback
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const googleConnected = params.get("google_connected");
    const googleError = params.get("google_error");
    const email = params.get("email");

    if (googleConnected === "success") {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time banner from the redirect
      setBannerMessage({
        type: "success",
        text: email
          ? `Successfully connected Google account (${email})! Gmail, Calendar & Drive are now active.`
          : "Google account connected successfully! Workspace integrations are active.",
      });
      void fetchGoogleStatus();
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (googleError) {
      setBannerMessage({ type: "error", text: `Google connection failed: ${decodeURIComponent(googleError)}` });
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, [fetchGoogleStatus]);

  const handleConnectGoogle = async () => {
    setConnectingGoogle(true);
    setBannerMessage(null);
    setActiveMenu(null);
    try {
      const returnPath = typeof window !== "undefined" ? window.location.pathname : "/";
      const url = await getGoogleAuthUrl(returnPath);
      if (url) {
        window.location.href = url;
      } else {
        setBannerMessage({
          type: "error",
          text: "Could not generate Google authorization link. Please check your backend connection.",
        });
        setConnectingGoogle(false);
      }
    } catch {
      setBannerMessage({ type: "error", text: "Failed to initiate Google sign-in." });
      setConnectingGoogle(false);
    }
  };

  const handleDisconnectGoogle = async () => {
    setConfirmingDisconnect(false);
    setDisconnectingGoogle(true);
    try {
      const ok = await disconnectGoogleAccount();
      if (ok) {
        setBannerMessage({ type: "success", text: "Google account disconnected. Workspace sync paused." });
        await fetchGoogleStatus();
      } else {
        setBannerMessage({ type: "error", text: "Failed to disconnect Google account from backend." });
      }
    } catch {
      setBannerMessage({ type: "error", text: "An error occurred while disconnecting." });
    } finally {
      setDisconnectingGoogle(false);
    }
  };

  if (!isOpen || !mounted) return null;

  const isGoogleConnected = Boolean(googleStatus?.connected);
  const googleUnknown = Boolean(googleStatus?.unreachable);
  const connectedEmail = googleStatus?.email || "Google Account";

  const retryButton = (
    <button type="button" onClick={() => void fetchAll()} className={PRIMARY_BUTTON}>
      Retry
    </button>
  );

  /** Gmail, Calendar and Drive share one Google connection, so they share one state, one menu action set. */
  const googleRow = (key: string, title: string, description: string, activeText: string, icon: React.ReactNode, iconClass: string) => {
    const statusLine = loadingGoogle
      ? "Checking connection status..."
      : googleUnknown
        ? "Could not check the connection status"
        : isGoogleConnected
          ? `${connectedEmail} · ${activeText}`
          : "Not connected";
    return (
      <ConnectionRow key={key} icon={icon} iconClass={iconClass} title={title} description={description} statusLine={statusLine}>
        {loadingGoogle ? (
          <Loader2 className="w-4 h-4 animate-spin text-zinc-400" aria-label="Checking" />
        ) : googleUnknown ? (
          retryButton
        ) : isGoogleConnected ? (
          <>
            <span className={BADGE}>
              <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
              Connected
            </span>
            <button
              type="button"
              aria-label={`More actions for ${title}`}
              aria-haspopup="menu"
              aria-expanded={activeMenu === key}
              onClick={() => setActiveMenu(activeMenu === key ? null : key)}
              className={KEBAB_BUTTON}
            >
              <MoreVertical className="w-4 h-4" />
            </button>
            {activeMenu === key && (
              <div role="menu" className="absolute right-0 top-full mt-1 w-38 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg shadow-lg py-1 z-20">
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleConnectGoogle}
                  disabled={connectingGoogle}
                  className={`${MENU_ITEM} text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800`}
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  Switch Account
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setActiveMenu(null);
                    setConfirmingDisconnect(true);
                  }}
                  disabled={disconnectingGoogle}
                  className={`${MENU_ITEM} text-red-600 hover:bg-red-50 dark:hover:bg-red-950/20`}
                >
                  <LogOut className="w-3.5 h-3.5" />
                  Disconnect
                </button>
              </div>
            )}
          </>
        ) : (
          <button type="button" onClick={handleConnectGoogle} disabled={connectingGoogle} className={PRIMARY_BUTTON}>
            {connectingGoogle ? <Loader2 className="w-3.5 h-3.5 animate-spin text-white dark:text-zinc-900" /> : "Connect"}
          </button>
        )}
      </ConnectionRow>
    );
  };

  const waStatusLine =
    whatsApp === undefined
      ? "Checking connection status..."
      : whatsApp === null
        ? "Could not check the connection status"
        : whatsApp.configured
          ? `Connected through ${whatsApp.provider} · set up on the server`
          : "Not connected · the server uses the built-in test provider";

  const brixxStatusLine =
    brixx === undefined
      ? "Checking sync status..."
      : brixx === null
        ? "Could not check the sync status"
        : brixx.lastRunAt === null
          ? "No sync has run yet"
          : brixx.stale
            ? `Sync is stale · last run ${formatStamp(new Date(brixx.lastRunAt))}`
            : `Last sync ${formatStamp(new Date(brixx.lastRunAt))} · ${brixx.totalRows.toLocaleString("nl-NL")} rows mirrored`;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity" onClick={onClose} />

      {/* Modal Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connections-title"
        className="relative w-full max-w-[530px] bg-white dark:bg-[#18181b] border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-xl overflow-hidden z-10 transition-all select-none p-6"
      >
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 shrink-0 mt-0.5">
              <LayoutGrid className="w-4 h-4 stroke-[2]" />
            </div>
            <div>
              <h2 id="connections-title" className="font-semibold text-[17px] text-zinc-900 dark:text-zinc-100 leading-tight">
                Connections & Integrations
              </h2>
              <p className="text-[12px] text-zinc-500 dark:text-zinc-400 mt-1">
                Active external channels powering EstateOS triage, scheduling & document filing
              </p>
            </div>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close connections"
            onClick={onClose}
            className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Dynamic Alert Banner */}
        {bannerMessage && (
          <div
            role={bannerMessage.type === "error" ? "alert" : "status"}
            className={`mt-4 p-3 rounded-xl border text-[12.5px] flex items-start justify-between gap-2.5 transition-all ${
              bannerMessage.type === "success"
                ? "bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800/40 text-emerald-800 dark:text-emerald-300"
                : "bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800/40 text-red-800 dark:text-red-300"
            }`}
          >
            <div className="flex items-center gap-2">
              {bannerMessage.type === "success" ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              ) : (
                <AlertCircle className="w-4 h-4 text-red-600 shrink-0" />
              )}
              <span>{bannerMessage.text}</span>
            </div>
            <button type="button" aria-label="Dismiss message" onClick={() => setBannerMessage(null)} className="p-0.5 hover:opacity-75 transition-opacity">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Disconnect confirmation (replaces the browser's confirm box) */}
        {confirmingDisconnect && (
          <div role="alertdialog" aria-label="Confirm disconnect" className="mt-4 p-3 rounded-xl border border-amber-200 dark:border-amber-800/40 bg-amber-50 dark:bg-amber-950/20 text-[12.5px] text-amber-900 dark:text-amber-200">
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <span>
                Disconnect this Google account? Gmail, Calendar and Drive are one connection, so all three stop syncing until you connect again.
              </span>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmingDisconnect(false)}
                className="px-3 py-1.5 rounded-lg text-[12px] font-medium border border-zinc-300 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleDisconnectGoogle()}
                className="px-3 py-1.5 rounded-lg text-[12px] font-medium bg-red-600 text-white cursor-pointer"
              >
                Disconnect
              </button>
            </div>
          </div>
        )}

        {/* Connections List */}
        <div className="mt-5 space-y-0 divide-y divide-zinc-100 dark:divide-zinc-800/80">
          {googleRow("gmail", "Gmail", "Tenant inquiries, service notices & statements", "Synced live", GMAIL_ICON, ICON_BOX)}
          {googleRow("cal", "Google Calendar", "Scheduled viewings, maintenance callouts & lease renewals", "Schedule sync enabled", CAL_ICON, ICON_BOX)}
          {googleRow("drive", "Google Drive", "Tenancy leases, compliance documents & inspection photos", "Document storage active", DRIVE_ICON, ICON_BOX)}

          <ConnectionRow
            icon={WA_ICON}
            iconClass={ICON_BOX}
            title="WhatsApp Business"
            description="Instant tenant dispatch & messaging"
            statusLine={waStatusLine}
          >
            {whatsApp === undefined ? (
              <Loader2 className="w-4 h-4 animate-spin text-zinc-400" aria-label="Checking" />
            ) : whatsApp === null ? (
              retryButton
            ) : (
              <span className={BADGE}>
                {whatsApp.configured ? <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" /> : null}
                {whatsApp.configured ? "Connected" : "Not set up"}
              </span>
            )}
          </ConnectionRow>

          <ConnectionRow
            icon={BRIXX_ICON}
            iconClass="w-10 h-10 rounded-xl bg-sky-500 shadow-2xs flex items-center justify-center shrink-0"
            title="BRIXX"
            description="Financial modeling, cash flow ledger & property forecasting"
            statusLine={brixxStatusLine}
          >
            {brixx === undefined ? (
              <Loader2 className="w-4 h-4 animate-spin text-zinc-400" aria-label="Checking" />
            ) : brixx === null ? (
              retryButton
            ) : (
              <span className={BADGE}>
                {brixx.lastRunAt !== null && !brixx.stale ? <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" /> : <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />}
                {brixx.lastRunAt === null ? "Not synced" : brixx.stale ? "Stale" : "Syncing"}
              </span>
            )}
          </ConnectionRow>
        </div>

        {/* Footer */}
        <div className="mt-6 pt-2 flex justify-end">
          <button type="button" onClick={onClose} className={PRIMARY_BUTTON}>
            Done
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

const ICON_BOX =
  "w-10 h-10 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800 shadow-2xs flex items-center justify-center shrink-0";

const GMAIL_ICON = (
      <svg className="w-5 h-5" viewBox="0 0 24 24">
        <path
          fill="#EA4335"
          d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"
        />
      </svg>
);

const CAL_ICON = (
      <div className="w-5 h-5 rounded-md border-2 border-blue-600 flex flex-col overflow-hidden">
        <div className="h-1.5 bg-blue-600 w-full" />
        <div className="flex-1 flex items-center justify-center text-[9px] font-bold text-blue-600 leading-none">
          31
        </div>
      </div>

);

const DRIVE_ICON = (
      <svg className="w-5 h-5" viewBox="0 0 24 24">
        <path fill="#4285F4" d="M14.7 3.5H9.3L2 16.2l2.7 4.7 7.4-12.8 2.6-4.6z" />
        <path fill="#FBBC05" d="M22 16.2L14.7 3.5h-5.4l7.3 12.7H22z" />
        <path fill="#34A853" d="M19.3 20.9H4.7L2 16.2h14.6l2.7 4.7z" />
      </svg>
);

const WA_ICON = (
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
);

const BRIXX_ICON = (
      <svg
        className="w-5 h-5 text-white"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect
          x="3.5"
          y="3.5"
          width="7"
          height="7"
          rx="1.5"
          fill="currentColor"
          fillOpacity="0.25"
        />
        <rect
          x="13.5"
          y="3.5"
          width="7"
          height="7"
          rx="1.5"
          fill="currentColor"
          fillOpacity="0.25"
        />
        <rect
          x="3.5"
          y="13.5"
          width="7"
          height="7"
          rx="1.5"
          fill="currentColor"
          fillOpacity="0.25"
        />
        <rect
          x="13.5"
          y="13.5"
          width="7"
          height="7"
          rx="1.5"
          fill="currentColor"
          fillOpacity="0.25"
        />
      </svg>
);
