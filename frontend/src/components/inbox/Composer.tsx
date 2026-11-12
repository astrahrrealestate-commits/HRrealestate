"use client";

import React, { useState, useEffect, useRef } from "react";
import { Check, RotateCcw, Send, ArrowRight, ChevronDown, SlidersHorizontal, MessageSquare, Mail, Maximize2, X, ExternalLink, Loader2, UserCheck, Mic, MicOff, Languages } from "lucide-react";
import Link from "next/link";
import { AstraIcon } from "@/components/ui/AstraBrand";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { DraftOption } from "@/types/dashboard";
import { DraftPersona } from "@/types/inbox";
import { createGmailDraft, translateText } from "@/lib/api";
import { TranslationToggle } from "@/components/inbox/TranslationToggle";
import { formatClock } from "@/lib/clock";
import { useVoiceInput } from "@/hooks/useVoiceInput";

export interface ComposerProps {
  /** Which thread this composer is for: text typed in one thread comes back when the owner returns to it. */
  threadKey?: string;
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
  threadKey,
  onSendManualReply,
  onUndo,
  isSent: initialSent = false,
  sentTimestamp,
  className,
}: ComposerProps) {
  const getDraftKey = (d: DraftOption, idx: number) => (d.id ? `${d.id}-${idx}` : `d${idx + 1}`);

  const [isSent, setIsSent] = useState(initialSent);
  const [content, setContent] = useState(() => draftText || (!initialSent && drafts.length > 0 ? drafts[0]?.text : ""));
  const [selectedDraftId, setSelectedDraftId] = useState<string>(() =>
    drafts.length > 0 ? getDraftKey(drafts[0], 0) : "d1-0"
  );
  const [activeChannel, setActiveChannel] = useState<string>(channel);
  const [isEditingFull, setIsEditingFull] = useState(false);
  const [fullEditText, setFullEditText] = useState("");
  const [undoSeconds, setUndoSeconds] = useState(30);
  const [isDraftingGmail, setIsDraftingGmail] = useState(false);
  const [expandedDraftThreadKey, setExpandedDraftThreadKey] = useState<string | null>(null);
  const [isMobileEnOpen, setIsMobileEnOpen] = useState(false);
  const [mobileEnResults, setMobileEnResults] = useState<Record<string, string | null>>({});
  const [mobileEnLoadingText, setMobileEnLoadingText] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const collapsedTextareaRef = useRef<HTMLTextAreaElement>(null);
  const typedByThread = useRef<Record<string, string>>({});
  const selectedDraftByThread = useRef<Record<string, string>>({});
  const key = threadKey ?? "";
  const threadKeyRef = useRef(key);
  const isEditingFullRef = useRef(isEditingFull);

  useEffect(() => {
    threadKeyRef.current = key;
  }, [key]);

  useEffect(() => {
    isEditingFullRef.current = isEditingFull;
  }, [isEditingFull]);

  const isDutchThread = (detectedLanguage || "").toLowerCase().includes("dutch") || drafts.some((d) => d.language === "nl");
  const {
    isListening,
    error: voiceError,
    speechLang,
    setSpeechLang,
    toggleVoiceInput,
    stopListening,
  } = useVoiceInput({
    initialLang: isDutchThread ? "nl" : "en",
    onTranscript: (liveText) => {
      typedByThread.current[threadKeyRef.current] = liveText;
      setContent(liveText);
      if (isEditingFullRef.current) {
        setFullEditText(liveText);
      }
    },
  });

  // The owner's own text, remembered per thread; an incoming draft or a re-render must never overwrite it.
  const [isTranslating, setIsTranslating] = useState(false);
  const [lastTranslation, setLastTranslation] = useState<{ from: string; to: string } | null>(null);
  const [translateNotice, setTranslateNotice] = useState<string | null>(null);

  const editContent = (value: string) => {
    typedByThread.current[key] = value;
    setContent(value);
    setTranslateNotice(null);
  };
  // Replace the box with the Dutch for what is in it; "Undo translation" brings the original back.
  const translateContentToDutch = async () => {
    const original = content.trim();
    if (!original || isTranslating) return;
    setIsTranslating(true);
    setTranslateNotice(null);
    const result = await translateText(original, "nl");
    if (result?.text) {
      setLastTranslation({ from: content, to: result.text });
      editContent(result.text);
    } else if (result && result.language !== "en") {
      setTranslateNotice("The text does not read as English, so there is nothing to translate.");
    } else {
      setTranslateNotice("Translation is not available right now.");
    }
    setIsTranslating(false);
  };
  const selectDraft = (d: DraftOption, idx: number) => {
    const draftKey = getDraftKey(d, idx);
    selectedDraftByThread.current[key] = draftKey;
    setSelectedDraftId(draftKey);
    editContent(d.text ?? "");
    setIsSent(false);
    if (collapsedTextareaRef.current) {
      collapsedTextareaRef.current.scrollTop = 0;
    }
  };
  const forgetTyped = () => {
    delete typedByThread.current[key];
    delete selectedDraftByThread.current[key];
  };
  const handleRejectClick = () => {
    forgetTyped();
    setExpandedDraftThreadKey(null);
    setIsMobileEnOpen(false);
    onReject?.();
  };

  const cleanPhone = (recipientPhone || "").replace(/[^0-9]/g, "");
  const effectiveEmail = recipientEmail || (recipientPhone && recipientPhone.includes("@") ? recipientPhone : "");

  const handleOpenWhatsApp = (overrideText?: string) => {
    if (!cleanPhone) return;
    const textToSend = overrideText !== undefined ? overrideText : (content || draftText || "");
    const waUrl = `https://wa.me/${cleanPhone}?text=${encodeURIComponent(textToSend)}`;
    window.open(waUrl, "_blank", "noopener,noreferrer");
  };

  const handleOpenGmail = async (overrideText?: string) => {
    if (!effectiveEmail || isDraftingGmail) return;
    const textToSend = overrideText !== undefined ? overrideText : (content || draftText || "");
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

  // Sync the proposed draft, channel and sent status when the thread or the draft changes. `drafts` is rebuilt on
  // every render of the parent, so only its first entry (primitives) is a dependency.
  const hasDrafts = drafts.length > 0;
  const firstDraftKey = hasDrafts ? (drafts[0]?.id ? `${drafts[0].id}-0` : "d1") : "d1";
  const firstDraftText = drafts[0]?.text;
  useEffect(() => {
    setIsSent(initialSent);
    setActiveChannel(channel);
    const typed = typedByThread.current[key];
    const rememberedDraft = selectedDraftByThread.current[key];
    if (!initialSent && hasDrafts) {
      setSelectedDraftId(rememberedDraft || firstDraftKey);
    }
    if (typed !== undefined && !initialSent) {
      setContent(typed);
      return;
    }
    setContent(draftText || (!initialSent && hasDrafts ? firstDraftText || "" : ""));
  }, [key, draftText, channel, hasDrafts, firstDraftKey, firstDraftText, initialSent]);

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
    if (!content.trim()) return;
    forgetTyped();
    setExpandedDraftThreadKey(null);
    setIsMobileEnOpen(false);
    if (isListening) stopListening();
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
    editContent(fullEditText);
    setIsEditingFull(false);
  };

  const handleSendNormal = () => {
    if (!content.trim()) return;
    if (isListening) stopListening();
    if (onSendManualReply) {
      onSendManualReply(content, activeChannel, replyingTo?.id);
      forgetTyped();
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
  const isMobileDraftsOpen = hasDraft && expandedDraftThreadKey === key;

  // Auto-grow the collapsed mobile input so multi-line drafts (after the greeting line) show immediately
  useEffect(() => {
    const el = collapsedTextareaRef.current;
    if (!el || isMobileDraftsOpen) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`;
  }, [content, isMobileDraftsOpen, hasDraft]);

  const currentCachedEn = drafts.find((d) => d.text.trim() === content.trim())?.englishMeaning;
  const mobileEnAvailable = drafts.some((d) => d.language === "nl") || Boolean(currentCachedEn);
  const mobileEnglishText = currentCachedEn ?? mobileEnResults[content];
  const mobileEnLoading = mobileEnLoadingText === content;
  const mobileEnFailed = !mobileEnLoading && !mobileEnglishText && content in mobileEnResults;

  const handleToggleMobileEn = async () => {
    const next = !isMobileEnOpen;
    setIsMobileEnOpen(next);
    if (next && !mobileEnglishText && !mobileEnLoading && content.trim()) {
      const targetText = content;
      setMobileEnLoadingText(targetText);
      const res = await translateText(targetText, "en");
      setMobileEnResults((prev) => ({ ...prev, [targetText]: res?.text ?? null }));
      setMobileEnLoadingText((cur) => (cur === targetText ? null : cur));
    }
  };

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
              Sent via {activeChannel === "gmail" ? "Gmail" : "WhatsApp"} · <span className="font-mono">{sentTimestamp || formatClock(new Date())}</span>
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
      {/* =================================================================== */}
      {/* MOBILE COMPOSER (Option 2 Default + Compact Draft Sheet on Expand)  */}
      {/* =================================================================== */}
      <div
        className={cn(
          "sm:hidden shrink-0 border-t border-[var(--line)] bg-[var(--pane)] px-3 pt-2.5 pb-2.5 flex flex-col gap-2 select-none",
          className
        )}
      >
        {/* Quoted Message Preview */}
        {replyingTo && (
          <div className="flex items-start justify-between gap-2 p-2 px-2.5 rounded-[10px] bg-[var(--selected)] border-l-2 border-l-[var(--accent)] border border-[var(--line)] text-xs">
            <div className="min-w-0">
              <span className="font-semibold text-[var(--ink)] block truncate text-[11px]">
                Replying to {replyingTo.sender}:
              </span>
              <p className="text-[var(--ink-2)] truncate line-clamp-1 italic text-[11px]">
                &ldquo;{replyingTo.text}&rdquo;
              </p>
            </div>
            {onClearReplyingTo && (
              <button
                type="button"
                onClick={onClearReplyingTo}
                className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] shrink-0 cursor-pointer"
                title="Cancel quote"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}

        {/* Live Voice Status Indicator */}
        {isListening && (
          <div className="flex items-center justify-between px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-[11px] text-cyan-700 dark:text-cyan-300 font-medium">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-ping inline-block" />
              <span>
                {speechLang === "nl"
                  ? "Luisteren naar spraak (Nederlands)..."
                  : "Listening to speech (English)..."}
              </span>
            </span>
            <button
              type="button"
              onClick={stopListening}
              className="text-[10.5px] font-bold underline cursor-pointer ml-2"
            >
              Stop
            </button>
          </div>
        )}

        {/* COLLAPSED STATE (Option 2): Centered Floating Draft Switcher Pill + Pre-filled Pill Chat Bar */}
        {!isMobileDraftsOpen ? (
          <>
            {hasDraft && (
              <div className="flex justify-center">
                <div className="inline-flex items-center gap-1 max-w-full px-2 py-1 rounded-full bg-[#EFF6FF] border border-[#BFDBFE]/80 shadow-[0_2px_8px_rgba(26,115,232,0.08)] text-[11.5px] overflow-x-auto">
                  <AstraIcon className="w-3.5 h-3.5 text-[#1a73e8] shrink-0 ml-1" />
                  {drafts && drafts.length > 0 ? (
                    <div className="flex items-center gap-0.5 shrink-0">
                      {drafts.map((d, idx) => {
                        const draftKey = getDraftKey(d, idx);
                        const isSelected = selectedDraftId === draftKey;
                        const label = `Draft ${idx + 1}`;
                        return (
                          <button
                            key={`mc-${draftKey}`}
                            type="button"
                            onClick={() => selectDraft(d, idx)}
                            className={cn(
                              "px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all cursor-pointer",
                              isSelected
                                ? "bg-[#1a73e8] text-white shadow-2xs"
                                : "text-[#1E293B] hover:bg-[#DBEAFE]"
                            )}
                          >
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <span className="font-medium text-[#0F172A] px-1 whitespace-nowrap">
                      Astra draft ready
                    </span>
                  )}
                  <span className="text-[#94A3B8] px-0.5">·</span>
                  {draftPersona && (
                    <Link
                      href="/settings?group=persona"
                      title={`Acting as ${draftPersona.actingAs} · ${draftPersona.name} v${draftPersona.version}`}
                      aria-label={`Acting as ${draftPersona.actingAs}`}
                      className="w-5 h-5 rounded-full bg-white border border-[#BFDBFE] text-[#1a73e8] flex items-center justify-center shrink-0 hover:bg-blue-50"
                    >
                      <UserCheck className="w-3 h-3 stroke-[2.2]" />
                    </Link>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setExpandedDraftThreadKey(key);
                      setIsMobileEnOpen(false);
                    }}
                    className="w-6 h-6 rounded-full inline-flex items-center justify-center text-[#1a73e8] hover:bg-[#DBEAFE] hover:text-[#1557b0] shrink-0 cursor-pointer transition-colors"
                    title="Open draft options, English translation, reject, and full editor"
                    aria-label="Draft options"
                  >
                    <SlidersHorizontal className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}

            {/* Single-Line / Auto-Growing WhatsApp-Style Chat Input Bar (Pre-filled with Draft 1 when available) */}
            <div className="flex items-end gap-2">
              {/* Mic + NL/EN Language Switcher */}
              <div className="relative shrink-0 flex items-center pb-0.5">
                <button
                  type="button"
                  onClick={() => toggleVoiceInput(content)}
                  className={cn(
                    "w-9 h-9 rounded-full flex items-center justify-center transition-all cursor-pointer",
                    isListening
                      ? "bg-cyan-500 text-black shadow-[0_0_12px_rgba(0,229,255,0.65)] animate-pulse"
                      : "bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[#0F172A]"
                  )}
                  title={isListening ? "Listening... tap to stop" : `Dictate (${speechLang === "nl" ? "Dutch" : "English"})`}
                  aria-label="Voice input"
                >
                  {isListening ? (
                    <MicOff className="w-4 h-4 stroke-[2.2]" />
                  ) : (
                    <Mic className="w-4 h-4 stroke-[2]" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"))}
                  className={cn(
                    "absolute -top-1 -right-1 px-1.5 py-0 rounded-full text-[9px] font-bold leading-[14px] shadow-2xs cursor-pointer",
                    speechLang === "nl"
                      ? "bg-[#1E293B] text-white"
                      : "bg-[#1a73e8] text-white"
                  )}
                  title={`Voice language: ${speechLang === "nl" ? "Dutch" : "English"} (tap to switch)`}
                >
                  {speechLang.toUpperCase()}
                </button>
              </div>

              {/* Unified Rounded Pill Input Pre-filled with Draft 1 + Embedded Channel Shortcut */}
              <div className="flex-1 min-w-0 flex items-end gap-1.5 bg-[#F1F5F9] border border-[#E2E8F0] focus-within:border-[#1a73e8] focus-within:bg-white rounded-[20px] pl-3.5 pr-1.5 py-1.5 transition-colors">
                <textarea
                  ref={collapsedTextareaRef}
                  rows={1}
                  value={content}
                  onChange={(e) => editContent(e.target.value)}
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
                  placeholder={activeChannel === "gmail" ? "Type a Gmail reply..." : "Type a WhatsApp reply..."}
                  className="w-full max-h-[132px] overflow-y-auto text-[14.5px] bg-transparent text-[var(--ink)] placeholder:text-[#94A3B8] focus:outline-none resize-none leading-[1.35] py-0.5"
                />

                {activeChannel === "whatsapp" && cleanPhone && (
                  <button
                    type="button"
                    onClick={() => handleOpenWhatsApp()}
                    className="w-7 h-7 rounded-full shrink-0 text-[#0F172A] hover:text-emerald-600 hover:bg-emerald-50 flex items-center justify-center transition-colors cursor-pointer mb-0.5"
                    title="Open in WhatsApp"
                    aria-label="Open in WhatsApp"
                  >
                    <MessageSquare className="w-4 h-4 stroke-[2]" />
                  </button>
                )}
                {activeChannel === "gmail" && effectiveEmail && (
                  <button
                    type="button"
                    onClick={() => handleOpenGmail()}
                    disabled={isDraftingGmail}
                    className="w-7 h-7 rounded-full shrink-0 text-[#0F172A] hover:text-[#1a73e8] hover:bg-blue-50 flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50 mb-0.5"
                    title={isReply ? "Reply in Gmail" : "Open in Gmail"}
                    aria-label="Open in Gmail"
                  >
                    {isDraftingGmail ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4 stroke-[2]" />}
                  </button>
                )}
              </div>

              {/* Solid Blue Circular Send Arrow Button */}
              <button
                type="button"
                onClick={() => {
                  if (hasDraft) {
                    handleAccept();
                  } else {
                    handleSendNormal();
                  }
                }}
                disabled={!content.trim()}
                className={cn(
                  "w-9 h-9 rounded-full shrink-0 flex items-center justify-center transition-all mb-0.5",
                  content.trim()
                    ? "bg-[#1a73e8] hover:bg-[#1557b0] text-white shadow-xs cursor-pointer active:scale-95"
                    : "bg-[#1a73e8]/85 text-white/90 opacity-60 cursor-not-allowed"
                )}
                title={hasDraft ? "Accept & send draft" : "Send message"}
                aria-label={hasDraft ? "Accept & send draft" : "Send message"}
              >
                <ArrowRight className="w-4 h-4 stroke-[2.4]" />
              </button>
            </div>
          </>
        ) : (
          /* EXPANDED DRAFT MODE (Mockup 1 Compact Dock) */
          <div className="flex flex-col gap-2">
            {/* Slim Top Draft Toolbar: Draft Switcher Tabs + EN / Reject / Expand / Collapse */}
            <div className="flex items-center justify-between gap-2">
              {drafts && drafts.length > 0 ? (
                <div className="flex items-center gap-0.5 bg-[var(--bg)] p-0.5 rounded-full border border-[var(--line)] overflow-x-auto max-w-full">
                  {drafts.map((d, idx) => {
                    const draftKey = getDraftKey(d, idx);
                    const isSelected = selectedDraftId === draftKey;
                    const label = `Draft ${idx + 1}`;
                    return (
                      <button
                        key={`m-draft-${draftKey}`}
                        type="button"
                        onClick={() => selectDraft(d, idx)}
                        className={cn(
                          "px-2.5 py-1 rounded-full text-[11px] font-medium whitespace-nowrap transition-colors cursor-pointer",
                          isSelected
                            ? "bg-[var(--pane)] text-[var(--accent-ink)] font-bold shadow-2xs border border-[var(--line)]"
                            : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                        )}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--ink)]">
                  <AstraIcon className="w-3.5 h-3.5 text-[#1a73e8]" />
                  <span>Astra Draft</span>
                </span>
              )}

              <div className="flex items-center gap-1 shrink-0">
                {draftPersona && (
                  <Link
                    href="/settings?group=persona"
                    title={`Acting as ${draftPersona.actingAs} · ${draftPersona.name} v${draftPersona.version}`}
                    className="h-7 px-2 rounded-full border border-[#BFDBFE] bg-[#EFF6FF] text-[#1a73e8] inline-flex items-center gap-1 text-[10.5px] font-semibold shrink-0"
                  >
                    <UserCheck className="w-3.5 h-3.5 stroke-[2.2]" />
                    <span>{draftPersona.actingAs}</span>
                  </Link>
                )}
                {mobileEnAvailable && (
                  <button
                    type="button"
                    onClick={() => void handleToggleMobileEn()}
                    className={cn(
                      "px-2 py-1 rounded-full text-[11px] font-bold border transition-colors cursor-pointer inline-flex items-center gap-1",
                      isMobileEnOpen
                        ? "bg-[#1a73e8]/10 text-[#1a73e8] border-[#1a73e8]/30"
                        : "bg-[var(--bg)] text-[var(--ink-2)] border-[var(--line)]"
                    )}
                    title="Show English translation"
                  >
                    <Languages className="w-3 h-3" />
                    <span>EN</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleRejectClick}
                  className="w-7 h-7 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[var(--ink-3)] hover:text-red-600 hover:border-red-300 flex items-center justify-center transition-colors cursor-pointer"
                  title="Reject draft"
                  aria-label="Reject draft"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={handleOpenFullEdit}
                  className="w-7 h-7 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center justify-center transition-colors cursor-pointer"
                  title="Full-screen editor"
                  aria-label="Expand full editor"
                >
                  <Maximize2 className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setExpandedDraftThreadKey(null)}
                  className="w-7 h-7 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[var(--ink-2)] hover:text-[var(--ink)] flex items-center justify-center transition-colors cursor-pointer"
                  title="Collapse to chat bar"
                  aria-label="Collapse drafts"
                >
                  <ChevronDown className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Optional English Translation Preview */}
            {isMobileEnOpen && (
              <div className="text-[11.5px] text-[var(--ink-2)] italic bg-[var(--bg)] border border-[var(--line)] rounded-[10px] px-2.5 py-2 whitespace-pre-line leading-snug max-h-[84px] overflow-y-auto">
                {mobileEnLoading && "Translating..."}
                {mobileEnFailed && "Translation unavailable right now."}
                {mobileEnglishText}
              </div>
            )}

            {/* Compact 3-line Draft Box with Tucked Voice + NL Pill */}
            <div className="relative rounded-[12px] bg-[var(--bg)] border border-[var(--line)] focus-within:border-[var(--ink)] focus-within:bg-[var(--pane)] transition-colors">
              <textarea
                ref={textareaRef}
                rows={3}
                value={content}
                onChange={(e) => editContent(e.target.value)}
                placeholder="Edit Astra draft..."
                className="w-full min-h-[76px] max-h-[135px] text-[15px] p-2.5 pr-18 bg-transparent text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none resize-none leading-snug"
              />
              <div className="absolute right-2 bottom-2 flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => toggleVoiceInput(content)}
                  className={cn(
                    "w-7 h-7 rounded-full flex items-center justify-center border transition-all cursor-pointer",
                    isListening
                      ? "bg-cyan-500 text-black border-cyan-400 animate-pulse"
                      : "bg-[var(--pane)] text-[var(--ink-2)] border-[var(--line)]"
                  )}
                  title={isListening ? "Stop dictation" : "Dictate draft edit"}
                >
                  {isListening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5 text-[var(--accent-ink)]" />}
                </button>
                <button
                  type="button"
                  onClick={() => setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"))}
                  className={cn(
                    "px-1.5 h-7 rounded-full text-[10px] font-bold border inline-flex items-center gap-1 cursor-pointer",
                    speechLang === "nl"
                      ? "bg-amber-500/15 text-amber-700 border-amber-500/30"
                      : "bg-blue-500/15 text-blue-700 border-blue-500/30"
                  )}
                  title="Switch dictation language"
                >
                  {speechLang === "nl" ? <FlagNL className="w-3 h-2" /> : <FlagUK className="w-3 h-2" />}
                  <span>{speechLang.toUpperCase()}</span>
                </button>
              </div>
            </div>

            {/* Single Side-by-Side Bottom Action Row */}
            <div className="flex items-center gap-2">
              {activeChannel === "whatsapp" && cleanPhone && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={() => handleOpenWhatsApp()}
                  className="shrink-0 h-10 px-3 rounded-full text-emerald-600 border-emerald-300 font-semibold text-xs"
                  icon={<ExternalLink className="w-3.5 h-3.5" />}
                >
                  WhatsApp
                </Button>
              )}
              {activeChannel === "gmail" && effectiveEmail && (
                <Button
                  variant="secondary"
                  size="default"
                  onClick={() => handleOpenGmail()}
                  disabled={isDraftingGmail}
                  className="shrink-0 h-10 px-3 rounded-full text-blue-600 border-blue-300 font-semibold text-xs"
                  icon={isDraftingGmail ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" /> : <ExternalLink className="w-3.5 h-3.5" />}
                >
                  {isDraftingGmail ? "Draft..." : "Gmail"}
                </Button>
              )}
              <Button
                variant="primary"
                size="default"
                onClick={handleAccept}
                className="flex-1 h-10 rounded-full font-semibold text-xs sm:text-sm"
                icon={<AstraIcon className="w-4 h-4" />}
              >
                Accept &amp; send
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* =================================================================== */}
      {/* DESKTOP COMPOSER (Unified clean card on sm:+)                       */}
      {/* =================================================================== */}
      <div
        className={cn(
          "hidden sm:flex shrink-0 border-t border-[var(--line)] bg-[var(--pane)] px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] flex-col select-none",
          className
        )}
      >
        <div className="rounded-[12px] border border-[var(--line)] bg-[var(--pane)] shadow-2xs focus-within:border-[var(--ink)] transition-colors overflow-hidden flex flex-col">
          {/* Top Integrated Composer Bar: Channel + Draft Switcher + Compact Persona */}
          <div className="px-3 py-2 border-b border-[var(--line)] bg-[var(--bg)]/60 flex items-center justify-between gap-2 flex-wrap text-xs text-[var(--ink-3)]">
            <div className="flex items-center gap-2 flex-wrap min-w-0">
              {/* Locked Channel Badge */}
              <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[var(--ink)] bg-[var(--pane)] border border-[var(--line)] px-2 py-0.5 rounded-[6px] shrink-0">
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

              {/* AI Draft Switcher Tabs */}
              {drafts && drafts.length > 0 && (
                <div className="flex items-center gap-0.5 bg-[var(--pane)] p-0.5 rounded-[7px] border border-[var(--line)]">
                  {drafts.map((d, idx) => {
                    const draftKey = getDraftKey(d, idx);
                    const isSelected = selectedDraftId === draftKey;
                    const label = `Draft ${idx + 1}`;
                    return (
                      <button
                        key={`draft-${draftKey}`}
                        type="button"
                        onClick={() => selectDraft(d, idx)}
                        className={cn(
                          "px-2.5 py-0.5 rounded-[5px] text-[11.5px] font-medium transition-colors cursor-pointer whitespace-nowrap",
                          isSelected
                            ? "bg-[var(--selected)] text-[var(--ink)] font-bold"
                            : "text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--bg)]"
                        )}
                        title={d.text}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              {drafts && drafts.length > 0 && draftPersona && (
                <Link
                  href="/settings?group=persona"
                  title={`Drafted using "${draftPersona.name}" (v${draftPersona.version}). Click to edit persona.`}
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--ink-2)] hover:text-[var(--ink)] bg-[var(--pane)] border border-[var(--line)] px-2 py-0.5 rounded-[6px] transition-colors whitespace-nowrap"
                >
                  <UserCheck className="w-3 h-3 text-[#1a73e8] shrink-0" />
                  <span>Acting as <strong className="font-semibold text-[var(--ink)]">{draftPersona.actingAs}</strong></span>
                </Link>
              )}
              {detectedLanguage && (
                <span
                  className="text-[10.5px] font-semibold text-[var(--ink-3)] bg-[var(--pane)] border border-[var(--line)] px-1.5 py-0.5 rounded-[6px] whitespace-nowrap"
                  title={detectedLanguage}
                >
                  {detectedLanguage.toLowerCase().includes("nl") || detectedLanguage.toLowerCase().includes("dutch")
                    ? "NL"
                    : detectedLanguage.toLowerCase().includes("en")
                      ? "EN"
                      : detectedLanguage}
                </span>
              )}
            </div>
          </div>

          {/* Quoted Message Preview if user selected a message to reply to */}
          {replyingTo && (
            <div className="mx-3 mt-2.5 flex items-start justify-between gap-2 p-2 px-3 rounded-[var(--radius-ctl)] bg-[var(--selected)] border-l-2 border-l-[var(--accent)] border border-[var(--line)] text-xs">
              <div className="min-w-0">
                <span className="font-semibold text-[var(--ink)] block truncate">
                  Replying to {replyingTo.sender}:
                </span>
                <p className="text-[var(--ink-2)] truncate line-clamp-1 italic text-[11.5px]">
                  &ldquo;{replyingTo.text}&rdquo;
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

          {/* Clean Open Writing Canvas */}
          <div className="relative bg-[var(--pane)]">
            <textarea
              ref={textareaRef}
              rows={hasDraft ? 4 : 3}
              value={content}
              onChange={(e) => editContent(e.target.value)}
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
              className="w-full min-h-[104px] text-[14px] px-3.5 py-2.5 bg-transparent border-0 text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none resize-y leading-relaxed"
            />
          </div>

          {/* Integrated Bottom Toolbar */}
          <div className="px-3 py-2 border-t border-[var(--line)] bg-[var(--bg)]/40 flex flex-wrap items-center justify-between gap-2">
            {/* Left utilities: Dictate + Lang + English toggle */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                type="button"
                onClick={() => toggleVoiceInput(content)}
                className={cn(
                  "px-2.5 py-1 rounded-[7px] text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 shrink-0 border select-none",
                  isListening
                    ? "bg-cyan-500 text-black border-cyan-400 shadow-[0_0_15px_rgba(0,229,255,0.7)] animate-pulse font-semibold ring-2 ring-cyan-300"
                    : "bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] hover:text-[var(--ink)] border-[var(--line)]"
                )}
                title={isListening ? "Listening... click to stop" : `Voice dictation (${speechLang === "nl" ? "Dutch" : "English"})`}
                aria-label="Voice input"
              >
                {isListening ? (
                  <MicOff className="w-3.5 h-3.5 text-black stroke-[2.5]" />
                ) : (
                  <Mic className="w-3.5 h-3.5 text-[var(--accent-ink)] stroke-[2]" />
                )}
                <span>{isListening ? "Listening..." : "Dictate"}</span>
              </button>

              <button
                type="button"
                onClick={() => setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"))}
                className={cn(
                  "text-[10.5px] font-bold px-2 py-1 rounded-[7px] border transition-all cursor-pointer flex items-center gap-1 select-none bg-[var(--pane)] hover:bg-[var(--selected)] border-[var(--line)] text-[var(--ink-2)]"
                )}
                title={speechLang === "nl" ? "Voice language: Nederlands (click to switch to English)" : "Voice language: English (click to switch to Nederlands)"}
              >
                <span className="inline-flex items-center gap-1">
                  {speechLang === "nl" ? <FlagNL className="w-3.5 h-2.5" /> : <FlagUK className="w-3.5 h-2.5" />}
                  <span>{speechLang === "nl" ? "NL" : "EN"}</span>
                </span>
              </button>

              {isListening && (
                <span className="text-[11.5px] text-cyan-600 dark:text-cyan-400 font-medium animate-pulse flex items-center gap-1.5 pl-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-ping inline-block" />
                  <span>
                    {speechLang === "nl"
                      ? "Luisteren (NL)..."
                      : "Listening (EN)..."}
                  </span>
                </span>
              )}

              {voiceError && !isListening && (
                <span className="text-[11.5px] text-amber-600 dark:text-amber-400 font-medium pl-1">{voiceError}</span>
              )}

              {/* Translate the box to Dutch: owner types English, the tenant reads Dutch. Local model, cached. */}
              {content.trim() && (
                <button
                  type="button"
                  onClick={() => void translateContentToDutch()}
                  disabled={isTranslating}
                  className="text-[10.5px] font-bold px-2 py-0.5 rounded-full border transition-all cursor-pointer flex items-center gap-1 select-none bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] hover:text-[var(--ink)] border-[var(--line)] disabled:opacity-60"
                  title="Translate the text in the box to Dutch before sending"
                >
                  {isTranslating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Languages className="w-3 h-3" />}
                  <span>{isTranslating ? "Vertalen…" : "Translate to Dutch"}</span>
                </button>
              )}
              {translateNotice && !isTranslating && (
                <span className="text-[11.5px] text-amber-600 dark:text-amber-400 font-medium pl-1">{translateNotice}</span>
              )}
              {lastTranslation && content === lastTranslation.to && (
                <button
                  type="button"
                  onClick={() => {
                    editContent(lastTranslation.from);
                    setLastTranslation(null);
                  }}
                  className="text-xs text-[var(--ink-3)] underline hover:text-[var(--ink)] cursor-pointer"
                >
                  Undo translation
                </button>
              )}

              <TranslationToggle
                text={content}
                language={drafts.find((d) => d.text.trim() === content.trim())?.language
                  ?? (drafts.some((d) => d.language === "nl") ? "nl" : undefined)}
                cachedEnglish={drafts.find((d) => d.text.trim() === content.trim())?.englishMeaning}
                cachedDutch={drafts.find((d) => d.text.trim() === content.trim())?.dutchMeaning}
              />
            </div>

            {/* Right actions */}
            {hasDraft ? (
              <div className="flex flex-wrap items-center gap-1.5 justify-end ml-auto">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleRejectClick}
                  className="text-[var(--ink-3)] hover:text-[var(--ink)] whitespace-nowrap shrink-0 h-8"
                >
                  Reject
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => textareaRef.current?.focus()}
                  className="whitespace-nowrap shrink-0 h-8"
                >
                  Edit
                </Button>
                {activeChannel === "whatsapp" && cleanPhone && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleOpenWhatsApp()}
                    className="whitespace-nowrap shrink-0 h-8 text-emerald-700 hover:text-emerald-800 bg-[var(--pane)] hover:bg-[var(--selected)] border border-[var(--line)] font-semibold cursor-pointer"
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
                    onClick={() => handleOpenGmail()}
                    disabled={isDraftingGmail}
                    className="whitespace-nowrap shrink-0 h-8 text-[var(--ink)] bg-[var(--pane)] hover:bg-[var(--selected)] border border-[var(--line)] font-semibold cursor-pointer"
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
                  className="whitespace-nowrap shrink-0 px-3.5 h-8 font-bold"
                  icon={<AstraIcon className="w-3.5 h-3.5" />}
                >
                  Accept &amp; send
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-1.5 justify-end ml-auto">
                {activeChannel === "whatsapp" && cleanPhone && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleOpenWhatsApp()}
                    disabled={!content.trim()}
                    className="whitespace-nowrap shrink-0 h-8 text-emerald-700 bg-[var(--pane)] hover:bg-[var(--selected)] border border-[var(--line)] font-semibold cursor-pointer"
                    icon={<ExternalLink className="w-3.5 h-3.5 text-emerald-600" />}
                    title="Open this message directly in WhatsApp Web or App"
                  >
                    Open in WhatsApp
                  </Button>
                )}
                {activeChannel === "gmail" && effectiveEmail && (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => handleOpenGmail()}
                    disabled={!content.trim() || isDraftingGmail}
                    className="whitespace-nowrap shrink-0 h-8 text-[var(--ink)] bg-[var(--pane)] hover:bg-[var(--selected)] border border-[var(--line)] font-semibold cursor-pointer"
                    icon={isDraftingGmail ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-600" /> : <ExternalLink className="w-3.5 h-3.5 text-blue-600" />}
                    title={isReply ? "Reply to this thread in Gmail" : "Compose a new email in Gmail"}
                  >
                    {isDraftingGmail ? "Preparing Draft..." : (isReply ? "Reply in Gmail" : "Open in Gmail")}
                  </Button>
                )}
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleSendNormal}
                  disabled={!content.trim()}
                  icon={<Send className="w-3.5 h-3.5 fill-current" />}
                  className="px-4 h-8 font-bold"
                >
                  Send
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Mobile Full-Height Editor Sheet (Section 5.6.1) */}
      {isEditingFull && (
        <div className="fixed inset-0 z-50 md:hidden bg-[var(--pane)] flex flex-col">
          <div className="h-14 px-4 border-b border-[var(--line)] flex items-center justify-between flex-shrink-0">
            <span className="font-heading font-bold text-[16px] text-[var(--ink)]">
              Edit AI Draft
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => toggleVoiceInput(fullEditText)}
                className={cn(
                  "p-1.5 rounded-full transition-all cursor-pointer flex items-center justify-center shrink-0 border",
                  isListening
                    ? "bg-cyan-500 text-black border-cyan-400 shadow-[0_0_12px_rgba(0,229,255,0.7)] animate-pulse"
                    : "bg-[var(--pane)] text-[var(--ink-2)] border-[var(--line)]"
                )}
                title={isListening ? "Listening... click to stop" : "Voice dictation"}
              >
                {isListening ? <MicOff className="w-4 h-4 stroke-[2.5]" /> : <Mic className="w-4 h-4 stroke-[2]" />}
              </button>
              <button
                type="button"
                onClick={() => {
                  stopListening();
                  setIsEditingFull(false);
                }}
                className="p-1 rounded text-[var(--ink-3)]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
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
