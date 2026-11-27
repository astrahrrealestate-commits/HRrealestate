"use client";

import React, { useEffect } from "react";
import { Mail, MessageSquare, Paperclip, SendHorizontal, X } from "lucide-react";

export interface SendConfirmModalProps {
  isOpen: boolean;
  channel: string;
  recipient?: string;
  subject?: string;
  body: string;
  attachmentCount?: number;
  isSending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Confirmation dialog shown before dispatching an email or WhatsApp message. */
export function SendConfirmModal({
  isOpen,
  channel,
  recipient,
  subject,
  body,
  attachmentCount = 0,
  isSending = false,
  onConfirm,
  onCancel,
}: SendConfirmModalProps) {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isSending) onCancel();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSending, onCancel]);

  if (!isOpen) return null;

  const isGmail = channel.toLowerCase() === "gmail" || channel.toLowerCase() === "email";
  const channelLabel = isGmail ? "Email (Gmail)" : "WhatsApp";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-[1px] p-4 animate-in fade-in duration-150"
      role="dialog"
      aria-modal="true"
      aria-labelledby="send-confirm-title"
      onClick={() => {
        if (!isSending) onCancel();
      }}
    >
      <div
        className="w-full max-w-md rounded-xl border border-[var(--line)] bg-[var(--pane)] text-[var(--ink)] shadow-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--line)]">
          <div className="flex items-center gap-2">
            {isGmail ? (
              <Mail className="w-4 h-4 text-[#1a73e8]" />
            ) : (
              <MessageSquare className="w-4 h-4 text-emerald-600" />
            )}
            <h2 id="send-confirm-title" className="text-sm font-semibold">
              Are you sure you want to send?
            </h2>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={isSending}
            aria-label="Close confirmation"
            className="p-1 rounded-md text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] cursor-pointer disabled:opacity-40"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={
                isGmail
                  ? "inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400"
                  : "inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              }
            >
              {channelLabel}
            </span>
            {recipient && (
              <span className="text-[var(--ink-2)] truncate max-w-[260px]" title={recipient}>
                To: <strong className="text-[var(--ink)] font-medium">{recipient}</strong>
              </span>
            )}
          </div>

          {isGmail && subject && (
            <div className="text-[11.5px] text-[var(--ink-3)] truncate" title={subject}>
              Thread: <span className="text-[var(--ink-2)] font-medium">{subject}</span>
            </div>
          )}

          <div className="rounded-lg border border-[var(--line)] bg-[var(--bg)] p-3 max-h-48 overflow-y-auto whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--ink)]">
            {body}
          </div>

          {attachmentCount > 0 && (
            <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--ink-2)]">
              <Paperclip className="w-3.5 h-3.5" />
              <span>
                {attachmentCount} attachment{attachmentCount === 1 ? "" : "s"} included
              </span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-[var(--line)] bg-[var(--bg)]/50">
          <button
            type="button"
            onClick={onCancel}
            disabled={isSending}
            className="px-3 py-1.5 rounded-lg border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-xs font-medium text-[var(--ink-2)] cursor-pointer disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isSending}
            className="px-3.5 py-1.5 rounded-lg bg-[#1a73e8] hover:bg-[#1557b0] text-white text-xs font-semibold inline-flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            <SendHorizontal className="w-3.5 h-3.5" />
            <span>{isSending ? "Sending..." : "Confirm & Send"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
