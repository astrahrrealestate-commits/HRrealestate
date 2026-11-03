"use client";

import React, { useState, useEffect, useRef } from "react";
import { Sparkles, Check, RotateCcw, Send, MessageSquare, Mail, Maximize2, X, ExternalLink, Loader2, UserRound } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { DraftOption } from "@/types/dashboard";
import { DraftPersona } from "@/types/inbox";
import { createGmailDraft } from "@/lib/api";

export interface ComposerProps {
  draftText?: string;
  drafts?: DraftOption[];
  draftPersona?: DraftPersona; // set when the drafts were written in the owner's persona
  detectedLanguage?: string;
  channel?: "whatsapp" | "gmail" | string;
  recipientPhone?: string;
  recipientEmail?: string;
  subject?: string;
  externalThreadId?: string;
  isReply?: boolean;
  replyingTo?: { id: string; text: string; sender: string } | null;
  onClearReplyingTo?: () => void;
  onAcceptAndSend?: (text: string, channel: string, replyToMessageId?: string) => void;
  onReject?: () => void;
  onSendManualReply?: (text: string, channel: string, replyToMessageId?: string) => void;
  onUndo?: () => void;
  isSent?: boolean;
  sentTimestamp?: string;
  className?: string;
}

/**
 * Composer implements Sections 5.2, 5.6, 5.6.1 & 6.2:
 * - Sticky at the bottom of the conversation, never scrolls away.
 * - State 1: AI draft ready with editable textarea, draft switcher tabs, Reject, Edit, Accept and send, Open in WhatsApp / Gmail.
 * - State 2: Sent state ("✓ Sent via WhatsApp / Gmail · 08:21 · Undo" for 30s).
 * - State 3: Normal reply input with channel indicator and "Draft with AI".
 * - Mobile responsive: 16px font (no iOS zoom), full-height edit sheet, mobile button stack.
 */
export function Composer({
  draftText = "",
  drafts = [],
  draftPersona,
  detectedLanguage = "Dutch (detected)",
  channel = "whatsapp",
  recipientPhone,
  recipientEmail,
  subject,
  externalThreadId,
  isReply = true,
  replyingTo = null,
  onClearReplyingTo,
  onAcceptAndSend,
  onReject,
  onSendManualReply,
  onUndo,
  isSent: initialSent = false,
  sentTimestamp,
  className,
}: ComposerProps) {
  const [isSent, setIsSent] = useState(initialSent);
  const [content, setContent] = useState(() => draftText || (!initialSent && drafts.length > 0 ? drafts[0]?.text : ""));
  const [selectedDraftId, setSelectedDraftId] = useState<string>(drafts[0]?.id || "d1");
  const [activeChannel, setActiveChannel] = useState<string>(channel);
  const [isEditingFull, setIsEditingFull] = useState(false);
  const [fullEditText, setFullEditText] = useState("");
  const [undoSeconds, setUndoSeconds] = useState(30);
  const [isDraftingGmail, setIsDraftingGmail] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const cleanPhone = (recipientPhone || "").replace(/[^0-9]/g, "");
  const effectiveEmail = recipientEmail || (recipientPhone && recipientPhone.includes("@") ? recipientPhone : "");

  const handleOpenWhatsApp = () => {
    if (!cleanPhone) return;
    const textToSend = content || draftText || "";
    const waUrl = `https://wa.me/${cleanPhone}?text=${encodeURIComponent(textToSend)}`;
    window.open(waUrl, "_blank", "noopener,noreferrer");
  };

  const handleOpenGmail = async () => {
    if (!effectiveEmail || isDraftingGmail) return;
    const textToSend = content || draftText || "";
    const baseSubject = subject || "Regarding your message - EstateOS";
    const subjectToSend = isReply && !baseSubject.toLowerCase().startsWith("re:")
      ? `Re: ${baseSubject}`
      : baseSubject;

    const isMobileDevice = typeof window !== "undefined" && /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    if (isMobileDevice) {
      window.location.href = `mailto:${encodeURIComponent(effectiveEmail)}?subject=${encodeURIComponent(subjectToSend)}&body=${encodeURIComponent(textToSend)}`;
      return;
    }

    setIsDraftingGmail(true);
    try {
      const res = await createGmailDraft({
        to_email: effectiveEmail,
        subject: subjectToSend,
        body: textToSend,
        thread_id: externalThreadId,
      });
      window.open(res.web_url, "_blank", "noopener,noreferrer");
    } catch {
      const fallbackUrl = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(effectiveEmail)}&su=${encodeURIComponent(subjectToSend)}&body=${encodeURIComponent(textToSend)}`;
      window.open(fallbackUrl, "_blank", "noopener,noreferrer");
    } finally {
      setIsDraftingGmail(false);
    }
  };

  // Sync draft prop changes & sent status changes when switching threads
  useEffect(() => {
    setIsSent(initialSent);
    setActiveChannel(channel);
    if (!initialSent && drafts.length > 0) {
      setSelectedDraftId(drafts[0].id);
      setContent(draftText || drafts[0]?.text || "");
    } else {
      setContent(draftText || "");
    }
  }, [draftText, channel, drafts, initialSent]);

  // Focus textarea when user quotes a message
  useEffect(() => {
    if (replyingTo) {
      textareaRef.current?.focus();
    }
  }, [replyingTo]);

  // Handle sent state countdown
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isSent && undoSeconds > 0) {
      timer = setInterval(() => {
        setUndoSeconds((prev) => prev - 1);
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isSent, undoSeconds]);

  const handleAccept = () => {
    if (onAcceptAndSend) {
      onAcceptAndSend(content, activeChannel, replyingTo?.id);
      setIsSent(true);
      setUndoSeconds(30);
    }
  };

  const handleUndo = () => {
    setIsSent(false);
    if (onUndo) {
      onUndo();
    }
  };

  const handleOpenFullEdit = () => {
    setFullEditText(content);
    setIsEditingFull(true);
  };

  const handleSaveFullEdit = () => {
    setContent(fullEditText);
    setIsEditingFull(false);
  };

  const handleSendNormal = () => {
    if (!content.trim()) return;
    if (onSendManualReply) {
      onSendManualReply(content, activeChannel, replyingTo?.id);
      setContent("");
      if (onClearReplyingTo) {
        onClearReplyingTo();
      }
      setIsSent(true);
      setUndoSeconds(30);
    }
  };

  // State 1: AI draft available or matching draft text (only if not already sent)
  const hasDraft = !isSent && (Boolean(draftText) || Boolean(content.trim() && drafts.length > 0));

  return (
    <>
      {/* Sent Status Banner (displays for 30s with Undo option) */}
      {isSent && undoSeconds > 0 && (
        <div
          className={cn(
            "shrink-0 border-t border-[var(--line)] bg-[var(--pane)] px-4 py-2.5 flex items-center justify-between text-[12.5px] animate-in fade-in duration-150 select-none",
            className
          )}
        >
          <div className="flex items-center gap-2 text-[var(--ink-2)]">
            <Check className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" strokeWidth={2.5} />
            <span>
              Sent via {activeChannel === "gmail" ? "Gmail" : "WhatsApp"} · <span className="font-mono">{sentTimestamp || new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            </span>
            <span className="text-[11px] text-[var(--ink-3)] font-mono">({undoSeconds}s)</span>
          </div>

          <button
            type="button"
            onClick={handleUndo}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--accent-ink)] hover:underline cursor-pointer py-1 px-2 rounded hover:bg-[var(--selected)]"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Undo</span>
          </button>
        </div>
      )}
      <div
        className={cn(
          "shrink-0 border-t border-[var(--line)] bg-[var(--pane)] p-3 sm:p-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] flex flex-col gap-2.5 select-none",
          className
        )}
      >
        {/* Composer Header: Channel badge + AI Draft Switcher tabs (ALWAYS visible when drafts exist!) */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-[var(--ink-3)]">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Locked Channel Badge */}
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] border border-[var(--line)] px-2.5 py-1 rounded">
              {activeChannel === "gmail" ? (
                <>
                  <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                  <span>Gmail</span>
                </>
              ) : (
                <>
                  <MessageSquare className="w-3.5 h-3.5 text-emerald-600" />
                  <span>WhatsApp</span>
                </>
              )}
            </span>

            {/* AI Draft Switcher Tabs: ALWAYS available whenever drafts are present */}
            {drafts && drafts.length > 0 && (
              <>
                <span className="text-[var(--line)]">|</span>
                <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[var(--ink-2)]">
                  <Sparkles className="w-3.5 h-3.5 text-[var(--accent)]" />
                  <span>AI drafts:</span>
                </span>
                {draftPersona && (
                  <Link
                    href="/settings?group=persona"
                    title={`Drafted using the persona file "${draftPersona.name}" (version ${draftPersona.version}). Click to view or edit it.`}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--accent-ink)] bg-[var(--selected)] border border-[var(--line)] px-2 py-0.5 rounded hover:bg-[var(--pane)]"
                  >
                    <UserRound className="w-3 h-3" />
                    <span>Acting as {draftPersona.actingAs}</span>
                    <span className="font-normal text-[var(--ink-3)]">
                      · {draftPersona.name} v{draftPersona.version}
                    </span>
                  </Link>
                )}
                <div className="flex items-center gap-1 bg-[var(--bg)] p-0.5 rounded-[var(--radius-ctl)] border border-[var(--line)]">
                  {drafts.map((d, idx) => {
                    const isSelected = selectedDraftId === (d.id || `d${idx + 1}`) || content.trim() === d.text.trim();
                    const label = d.label
                      ? d.label.includes("1")
                        ? "Draft 1"
                        : d.label.includes("2")
                        ? "Draft 2"
                        : `Draft ${idx + 1}`
                      : `Draft ${idx + 1}`;
                    return (
                      <button
                        key={d.id || `draft-${idx}`}
                        type="button"
                        onClick={() => {
                          setSelectedDraftId(d.id || `d${idx + 1}`);
                          setContent(d.text);
                          setIsSent(false);
                        }}
                        className={cn(
                          "px-2.5 py-1 rounded text-[11.5px] font-medium transition-colors cursor-pointer",
                          isSelected
                            ? "bg-[var(--pane)] text-[var(--ink)] font-bold shadow-2xs border border-[var(--line)] text-[var(--accent-ink)]"
                            : "text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--pane)]"
                        )}
                        title={d.text}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          <div className="flex items-center gap-2 self-end sm:self-auto">
            <span className="text-[11px] text-[var(--ink-3)] hidden sm:inline">{detectedLanguage}</span>
            {/* Mobile Expand Button */}
            <button
              type="button"
              onClick={handleOpenFullEdit}
              className="md:hidden inline-flex items-center gap-1 text-[var(--ink-3)] hover:text-[var(--ink)]"
              title="Expand full screen editor"
            >
              <Maximize2 className="w-3 h-3" />
              <span>Expand</span>
            </button>
          </div>
        </div>

        {/* Quoted Message Preview if user selected a message to reply to */}
        {replyingTo && (
          <div className="flex items-start justify-between gap-2 p-2 px-3 rounded-[var(--radius-ctl)] bg-[var(--selected)] border-l-2 border-l-[var(--accent)] border border-[var(--line)] text-xs">
            <div className="min-w-0">
              <span className="font-semibold text-[var(--ink)] block truncate">
                Replying to {replyingTo.sender}:
              </span>
              <p className="text-[var(--ink-2)] truncate line-clamp-1 italic text-[11.5px]">
                "{replyingTo.text}"
              </p>
            </div>
            {onClearReplyingTo && (
              <button
                type="button"
                onClick={onClearReplyingTo}
                className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--pane)] shrink-0 cursor-pointer"
                title="Cancel quote"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Text Area (Enlarged size for comfortable reading and editing) */}
        <div className="relative">
          <textarea
            ref={textareaRef}
            rows={hasDraft ? 5 : 3}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (hasDraft) {
                  handleAccept();
                } else {
                  handleSendNormal();
                }
              }
            }}
            placeholder="Type a reply... (Press Enter to send)"
            className="w-full min-h-[96px] sm:min-h-[110px] text-base sm:text-[14px] p-3 rounded-[var(--radius-ctl)] bg-[var(--bg)] border border-[var(--line)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:bg-[var(--pane)] focus:border-[var(--ink)] focus:outline-none transition-colors resize-y leading-relaxed"
          />
        </div>

        {/* Bottom Bar: Action proposal & Buttons */}
        {hasDraft ? (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-0.5 min-w-0">
            <span className="text-[11.5px] text-[var(--ink-3)] truncate hidden sm:inline min-w-0 flex-1">
              On accept: escalate · dispatch approved contractor · reply · log
            </span>

            {/* Desktop: Reject | Edit | Open in WhatsApp | Accept and send */}
            <div className="hidden sm:flex items-center gap-2 justify-end shrink-0">
              <Button
                variant="ghost"
                size="sm"
                onClick={onReject}
                className="text-[var(--ink-3)] hover:text-[var(--ink)] whitespace-nowrap shrink-0"
              >
                Reject
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => textareaRef.current?.focus()}
                className="whitespace-nowrap shrink-0"
              >
                Edit
              </Button>
              {activeChannel === "whatsapp" && cleanPhone && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleOpenWhatsApp}
                  className="whitespace-nowrap shrink-0 text-emerald-600 hover:text-emerald-700 bg-emerald-50/60 hover:bg-emerald-100/60 dark:bg-emerald-950/20 dark:hover:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 font-semibold cursor-pointer"
                  icon={<ExternalLink className="w-3.5 h-3.5 text-emerald-600" />}
                  title="Open this drafted reply directly in WhatsApp Web or App"
                >
                  Open in WhatsApp
                </Button>
              )}
              {activeChannel === "gmail" && effectiveEmail && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleOpenGmail}
                  disabled={isDraftingGmail}
                  className="whitespace-nowrap shrink-0 text-blue-600 hover:text-blue-700 bg-blue-50/60 hover:bg-blue-100/60 dark:bg-blue-950/20 dark:hover:bg-blue-950/40 border border-blue-300 dark:border-blue-800 font-semibold cursor-pointer"
                  icon={isDraftingGmail ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" /> : <ExternalLink className="w-3.5 h-3.5 text-blue-600" />}
                  title={isReply ? "Reply to this thread in Gmail" : "Compose a new email in Gmail"}
                >
                  {isDraftingGmail ? "Preparing Draft..." : (isReply ? "Reply in Gmail" : "Open in Gmail")}
                </Button>
              )}
              <Button
                variant="primary"
                size="sm"
                onClick={handleAccept}
                className="whitespace-nowrap shrink-0 px-3.5 h-8.5 font-bold"
                icon={<Sparkles className="w-3.5 h-3.5 fill-[#0A0A0A]" />}
              >
                Accept & send
              </Button>
            </div>

            {/* Mobile Stack (Section 5.6): Ghost buttons above, full-width orange below */}
            <div className="sm:hidden flex flex-col gap-2">
              <div className="grid grid-cols-2 gap-2">
                <Button variant="ghost" size="sm" onClick={onReject}>
                  Reject
                </Button>
                <Button variant="ghost" size="sm" onClick={handleOpenFullEdit}>
                  Edit
                </Button>
              </div>
              {activeChannel === "whatsapp" && cleanPhone && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={handleOpenWhatsApp}
                  className="w-full text-emerald-600 border-emerald-300 font-semibold"
                  icon={<ExternalLink className="w-3.5 h-3.5" />}
                >
                  Open in WhatsApp
                </Button>
              )}
              {activeChannel === "gmail" && effectiveEmail && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={handleOpenGmail}
                  disabled={isDraftingGmail}
                  className="w-full text-blue-600 border-blue-300 font-semibold"
                  icon={isDraftingGmail ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" /> : <ExternalLink className="w-3.5 h-3.5" />}
                >
                  {isDraftingGmail ? "Preparing Draft..." : (isReply ? "Reply in Gmail" : "Open in Gmail")}
                </Button>
              )}
              <Button
                variant="primary"
                size="default"
                onClick={handleAccept}
                className="w-full h-11"
                icon={<Sparkles className="w-4 h-4 fill-[#0A0A0A]" />}
              >
                Accept and send
              </Button>
            </div>
          </div>
        ) : (
          /* Normal Send Bar */
          <div className="flex items-center justify-between gap-2 pt-1">
            <span className="text-[11.5px] text-[var(--ink-3)] hidden sm:inline">
              Press <kbd className="px-1.5 py-0.5 rounded border border-[var(--line)] bg-[var(--card)] font-mono text-[10px]">Enter</kbd> to send, <kbd className="px-1.5 py-0.5 rounded border border-[var(--line)] bg-[var(--card)] font-mono text-[10px]">Shift+Enter</kbd> for newline
            </span>
            <div className="flex items-center gap-2">
              {activeChannel === "whatsapp" && cleanPhone && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={handleOpenWhatsApp}
                  disabled={!content.trim()}
                  className="text-emerald-600 hover:text-emerald-700 bg-emerald-50/60 hover:bg-emerald-100/60 dark:bg-emerald-950/20 dark:hover:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 font-semibold cursor-pointer"
                  icon={<ExternalLink className="w-3.5 h-3.5 text-emerald-600" />}
                  title="Open this message directly in WhatsApp Web or App"
                >
                  Open in WhatsApp
                </Button>
              )}
              {activeChannel === "gmail" && effectiveEmail && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={handleOpenGmail}
                  disabled={!content.trim() || isDraftingGmail}
                  className="text-blue-600 hover:text-blue-700 bg-blue-50/60 hover:bg-blue-100/60 dark:bg-blue-950/20 dark:hover:bg-blue-950/40 border border-blue-300 dark:border-blue-800 font-semibold cursor-pointer"
                  icon={isDraftingGmail ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" /> : <ExternalLink className="w-3.5 h-3.5 text-blue-600" />}
                  title={isReply ? "Reply to this thread in Gmail" : "Compose a new email in Gmail"}
                >
                  {isDraftingGmail ? "Preparing Draft..." : (isReply ? "Reply in Gmail" : "Open in Gmail")}
                </Button>
              )}
              <Button
                variant="primary"
                size="default"
                onClick={handleSendNormal}
                disabled={!content.trim()}
                icon={<Send className="w-3.5 h-3.5 fill-current" />}
                className="px-4 font-bold"
              >
                Send
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Mobile Full-Height Editor Sheet (Section 5.6.1) */}
      {isEditingFull && (
        <div className="fixed inset-0 z-50 md:hidden bg-[var(--pane)] flex flex-col">
          <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between flex-shrink-0">
            <span className="font-heading font-bold text-[16px] text-[var(--ink)]">
              Edit AI Draft
            </span>
            <button
              type="button"
              onClick={() => setIsEditingFull(false)}
              className="p-1 rounded text-[var(--ink-3)]"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="flex-1 p-4 flex flex-col">
            <textarea
              autoFocus
              value={fullEditText}
              onChange={(e) => setFullEditText(e.target.value)}
              className="flex-1 w-full text-base p-3 bg-[var(--bg)] border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink)] focus:outline-none focus:border-[var(--ink)] resize-none"
            />
          </div>

          <div className="p-4 border-t border-[var(--line)] flex gap-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <Button
              variant="ghost"
              size="default"
              className="flex-1"
              onClick={() => setIsEditingFull(false)}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="default"
              className="flex-1"
              onClick={handleSaveFullEdit}
            >
              Save Draft
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
