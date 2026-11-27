"use client";

import React, { useState, useEffect, useRef } from "react";
import { Check, RotateCcw, Send, ArrowRight, ChevronDown, SlidersHorizontal, MessageSquare, Mail, Maximize2, X, ExternalLink, Loader2, UserCheck, Mic, MicOff, Languages, Sparkles, Paperclip, FileText } from "lucide-react";
import Link from "next/link";
import { AstraIcon } from "@/components/ui/AstraBrand";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { DraftOption } from "@/types/dashboard";
import { DraftPersona } from "@/types/inbox";
import { createGmailDraft, enhanceThreadDraft, translateText, uploadThreadAttachment, UploadedThreadAttachment } from "@/lib/api";
import { TranslationToggle } from "@/components/inbox/TranslationToggle";
import { DraftCommitments } from "@/components/inbox/DraftCommitments";
import { formatClock } from "@/lib/clock";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useLanguage } from "@/context/LanguageContext";

const MOBILE_COLLAPSED_MAX_HEIGHT = 180;
const MOBILE_EXPANDED_MAX_HEIGHT = 240;
const DESKTOP_DEFAULT_MAX_HEIGHT = 220;

function desktopComposerMaxHeight(): number {
  if (typeof window === "undefined") return DESKTOP_DEFAULT_MAX_HEIGHT;
  return Math.min(Math.max(Math.round(window.innerHeight * 0.28), 160), 230);
}

/** Resize a composer textarea smoothly to fit its content up to `maxHeightPx`, shrinking back when text decreases. */
function syncTextareaHeight(
  el: HTMLTextAreaElement | null,
  maxHeightPx: number,
  pinCursorEnd = false
): void {
  if (!el) return;
  el.style.height = "auto";
  const nextHeight = Math.min(el.scrollHeight, maxHeightPx);
  el.style.height = `${nextHeight}px`;
  el.style.overflowY = el.scrollHeight > maxHeightPx ? "auto" : "hidden";
  if (pinCursorEnd && el.scrollHeight > maxHeightPx) {
    el.scrollTop = el.scrollHeight;
  }
}

function shouldPinComposerEnd(el: HTMLTextAreaElement, isListening: boolean): boolean {
  if (isListening) return true;
  return document.activeElement === el && el.selectionStart >= el.value.length - 1;
}

export interface ComposerProps {
  /** Which thread this composer is for: text typed in one thread comes back when the owner returns to it. */
  threadKey?: string;
  caseId?: string;
  targetMessageId?: string;
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
  onAcceptAndSend?: (text: string, channel: string, replyToMessageId?: string, attachmentIds?: string[]) => void;
  onReject?: () => void;
  onSendManualReply?: (text: string, channel: string, replyToMessageId?: string, attachmentIds?: string[]) => void;
  onEnhanced?: () => void;
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
  caseId,
  targetMessageId,
  onSendManualReply,
  onEnhanced,
  onUndo,
  isSent: initialSent = false,
  sentTimestamp,
  className,
}: ComposerProps) {
  const { t } = useLanguage();
  const getDraftKey = (d: DraftOption, idx: number) => (d.id ? `${d.id}-${idx}` : `d${idx + 1}`);

  const [isSent, setIsSent] = useState(initialSent);
  const [content, setContent] = useState(() => draftText || (!initialSent && drafts.length > 0 ? drafts[0]?.text : ""));
  const [selectedDraftId, setSelectedDraftId] = useState<string>(() =>
    drafts.length > 0 ? getDraftKey(drafts[0], 0) : "d1-0"
  );
  const [activeChannel, setActiveChannel] = useState<string>(channel);
  const [isEditingFull, setIsEditingFull] = useState(false);
  const [isDesktopExpanded, setIsDesktopExpanded] = useState(false);
  const [fullEditText, setFullEditText] = useState("");
  const [undoSeconds, setUndoSeconds] = useState(30);
  const [isDraftingGmail, setIsDraftingGmail] = useState(false);
  const [expandedDraftThreadKey, setExpandedDraftThreadKey] = useState<string | null>(null);
  const [isMobileEnOpen, setIsMobileEnOpen] = useState(false);
  const [mobileEnResults, setMobileEnResults] = useState<Record<string, string | null>>({});
  const [mobileEnLoadingText, setMobileEnLoadingText] = useState<string | null>(null);
  const [enhancePrompt, setEnhancePrompt] = useState("");
  const [isEnhancing, setIsEnhancing] = useState(false);
  const [enhanceError, setEnhanceError] = useState<string | null>(null);
  const [enhanceSources, setEnhanceSources] = useState<string[]>([]);
  const [lastEnhance, setLastEnhance] = useState<{ from: string; to: string } | null>(null);
  const [enhancedDraftsState, setEnhancedDraftsState] = useState<{ threadKey: string; drafts: DraftOption[] } | null>(null);
  const desktopTextareaRef = useRef<HTMLTextAreaElement>(null);
  const mobileExpandedTextareaRef = useRef<HTMLTextAreaElement>(null);
  const collapsedTextareaRef = useRef<HTMLTextAreaElement>(null);
  const enhanceTextareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachments, setAttachments] = useState<UploadedThreadAttachment[]>([]);
  const [isUploadingAttachment, setIsUploadingAttachment] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const typedByThread = useRef<Record<string, string>>({});
  const selectedDraftByThread = useRef<Record<string, string>>({});
  const desktopCollapsedByThread = useRef<Record<string, boolean>>({});
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

  const enhanceVoice = useVoiceInput({
    initialLang: isDutchThread ? "nl" : "en",
    onTranscript: (liveText) => {
      setEnhancePrompt(liveText);
      setEnhanceError(null);
    },
  });
  const effectiveDrafts =
    enhancedDraftsState && enhancedDraftsState.threadKey === key ? enhancedDraftsState.drafts : drafts;

  const handleEnhance = async (instructionOverride?: string) => {
    const instruction = (instructionOverride ?? enhancePrompt).trim();
    const targetCaseId = caseId || key;
    if (!instruction || !targetCaseId || isEnhancing) return;
    if (enhanceVoice.isListening) enhanceVoice.stopListening();
    setIsEnhancing(true);
    setEnhanceError(null);
    const previous = content;
    const res = await enhanceThreadDraft(targetCaseId, {
      instruction,
      current_text: content,
      message_id: targetMessageId,
    });
    setIsEnhancing(false);
    if (!res.ok || !res.draftText) {
      setEnhanceError(res.problem || "Could not enhance draft.");
      return;
    }
    const nextVariants = res.variants.length > 0 ? res.variants : [res.draftText];
    const baseDraft = drafts[0];
    const nextDrafts: DraftOption[] = nextVariants.map((text, idx) => ({
      id: `${activeChannel === "whatsapp" ? "wd" : "gd"}${idx + 1}`,
      version: res.draftVersion ?? (baseDraft?.version ?? 0) + 1,
      label: idx === 0 ? "Draft 1 (Recommended)" : "Draft 2 (Alternative)",
      channel: activeChannel === "whatsapp" ? "whatsapp" : "gmail",
      text,
      tone: baseDraft?.tone ?? "professional",
      recipientType: baseDraft?.recipientType ?? "tenant",
      recipientName: baseDraft?.recipientName ?? "",
      commitments: res.commitmentsByVariant?.[idx] ?? res.commitments,
    }));
    const firstKey = getDraftKey(nextDrafts[0], 0);
    setEnhancedDraftsState({ threadKey: key, drafts: nextDrafts });
    selectedDraftByThread.current[key] = firstKey;
    setSelectedDraftId(firstKey);
    editContent(nextVariants[0]);
    setLastEnhance({ from: previous, to: nextVariants[0] });
    setEnhanceSources(res.sourcesUsed ?? []);
    if (!instructionOverride) setEnhancePrompt("");
    onEnhanced?.();
  };

  const handleFilesSelected = async (files: FileList | File[] | null) => {
    const list = files ? Array.from(files) : [];
    const targetCaseId = caseId || key;
    if (list.length === 0 || !targetCaseId) return;
    setIsUploadingAttachment(true);
    setAttachError(null);
    for (const file of list) {
      const res = await uploadThreadAttachment(targetCaseId, file);
      if (res.ok && res.attachmentId) {
        setAttachments((prev) =>
          prev.some((a) => a.attachmentId === res.attachmentId) ? prev : [...prev, res]
        );
      } else {
        setAttachError(res.problem || `Failed to upload ${file.name}`);
      }
    }
    setIsUploadingAttachment(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const renderAttachmentChips = () => {
    if (attachments.length === 0 && !attachError && !isUploadingAttachment) return null;
    return (
      <div className="flex flex-wrap items-center gap-1.5 px-3 pb-2">
        {attachments.map((att) => (
          <span
            key={att.attachmentId}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[var(--line)] bg-[var(--bg)] text-[11px] text-[var(--ink)] shadow-2xs"
            title={`${att.filename} (${Math.max(1, Math.round(att.sizeBytes / 1024))} KB) · Synced to Drive`}
          >
            <FileText className="w-3 h-3 text-[#1a73e8] shrink-0" />
            <span className="truncate max-w-[160px] font-medium">{att.filename}</span>
            {activeChannel === "whatsapp" && !att.whatsappAllowed && (
              <span className="text-[10px] text-amber-600 font-semibold">(Too large for WA)</span>
            )}
            <button
              type="button"
              onClick={() =>
                setAttachments((prev) => prev.filter((item) => item.attachmentId !== att.attachmentId))
              }
              aria-label={`Remove ${att.filename}`}
              className="p-0.5 rounded-full hover:bg-[var(--selected)] text-[var(--ink-3)] hover:text-[var(--ink)] cursor-pointer"
            >
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        {isUploadingAttachment && (
          <span className="inline-flex items-center gap-1 text-[11px] text-[#1a73e8] font-medium px-2 py-0.5">
            <Loader2 className="w-3 h-3 animate-spin" />
            <span>Uploading to Drive &amp; thread...</span>
          </span>
        )}
        {attachError && <span className="text-[11px] text-red-600 font-medium">{attachError}</span>}
      </div>
    );
  };

  const renderEnhanceBar = (compact = false) => {
    if (!caseId && !key) return null;
    return (
      <div
        className={cn(
          "rounded-2xl border border-[var(--line)] bg-[var(--pane)] shadow-[0_4px_16px_rgba(10,27,47,0.06)] focus-within:border-[#1a73e8] focus-within:ring-2 focus-within:ring-[#1a73e8]/15 transition-all space-y-1.5",
          compact ? "px-2.5 py-2" : "px-3 py-2"
        )}
      >
        <div className="flex items-start gap-2 w-full">
          <Sparkles className="w-3.5 h-3.5 text-[#1a73e8] shrink-0 mt-1" />
          <textarea
            ref={enhanceTextareaRef}
            rows={1}
            value={enhancePrompt}
            onChange={(e) => {
              setEnhancePrompt(e.target.value);
              setEnhanceError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleEnhance();
              }
            }}
            placeholder={
              compact
                ? "Enhance draft (e.g. shorter, check lease)..."
                : "Enhance draft (e.g. shorter, check lease, add WWS rule)..."
            }
            disabled={isEnhancing}
            className="w-full min-h-[24px] max-h-[120px] bg-transparent text-[12.5px] leading-snug py-0.5 text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none resize-none overflow-y-auto"
          />
        </div>

        <div className="flex items-center justify-between gap-2 flex-wrap pt-0.5">
          <div className="flex items-center gap-1 flex-wrap min-w-0">
            {!enhancePrompt.trim() && !isEnhancing && (
              <>
                {(["Shorter", "Firmer", "More polite"] as const).map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => void handleEnhance(chip)}
                    className="text-[10.5px] font-medium px-2 py-0.5 rounded-full border border-[var(--line)] bg-[var(--bg)] hover:bg-[var(--selected)] text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer whitespace-nowrap"
                  >
                    {chip}
                  </button>
                ))}
              </>
            )}
            {enhanceError && <span className="text-[11px] text-red-600 font-medium">{enhanceError}</span>}
            {!enhanceError && enhanceSources.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[10.5px] text-[var(--ink-3)] font-medium">Sources:</span>
                {enhanceSources.slice(0, 3).map((src) => (
                  <span
                    key={src}
                    className="px-2 py-0.5 rounded-full bg-[var(--bg)] border border-[var(--line)] text-[10px] text-[var(--ink-2)] truncate max-w-[150px]"
                    title={src}
                  >
                    {src}
                  </span>
                ))}
              </div>
            )}
            {lastEnhance && content === lastEnhance.to && (
              <button
                type="button"
                onClick={() => {
                  editContent(lastEnhance.from);
                  setLastEnhance(null);
                }}
                className="text-[11px] text-[var(--ink-3)] underline hover:text-[var(--ink)] cursor-pointer shrink-0 ml-1"
              >
                Undo enhance
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            <button
              type="button"
              onClick={() => enhanceVoice.toggleVoiceInput(enhancePrompt)}
              disabled={isEnhancing}
              className={cn(
                "p-1.5 rounded-full transition-all cursor-pointer shrink-0 border",
                enhanceVoice.isListening
                  ? "bg-cyan-500 text-black border-cyan-400 animate-pulse"
                  : "bg-[var(--bg)] border-[var(--line)] text-[var(--ink-2)] hover:text-[var(--ink)]"
              )}
              title={
                enhanceVoice.isListening
                  ? "Stop dictating instruction"
                  : `Dictate instruction (${enhanceVoice.speechLang === "nl" ? "Dutch" : "English"})`
              }
              aria-label="Dictate enhancement instruction"
            >
              {enhanceVoice.isListening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
            </button>
            <button
              type="button"
              onClick={() => enhanceVoice.setSpeechLang((prev) => (prev === "nl" ? "en" : "nl"))}
              className="text-[10px] font-bold px-2 py-1 rounded-full border border-[var(--line)] bg-[var(--bg)] hover:bg-[var(--selected)] text-[var(--ink-2)] cursor-pointer inline-flex items-center gap-1 shrink-0"
              title="Switch instruction voice language (NL / EN)"
            >
              {enhanceVoice.speechLang === "nl" ? (
                <FlagNL className="w-3 h-2" />
              ) : (
                <FlagUK className="w-3 h-2" />
              )}
              <span>{enhanceVoice.speechLang === "nl" ? "NL" : "EN"}</span>
            </button>
            <button
              type="button"
              onClick={() => void handleEnhance()}
              disabled={isEnhancing || !enhancePrompt.trim()}
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#1a73e8] text-white hover:bg-[#1557b0] disabled:opacity-45 cursor-pointer inline-flex items-center gap-1 shrink-0 shadow-2xs"
            >
              {isEnhancing ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />}
              <span>{isEnhancing ? "Enhancing..." : "Enhance"}</span>
            </button>
          </div>
        </div>
      </div>
    );
  };

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
    for (const ref of [collapsedTextareaRef, mobileExpandedTextareaRef, desktopTextareaRef]) {
      if (ref.current) ref.current.scrollTop = 0;
    }
  };
  const forgetTyped = () => {
    delete typedByThread.current[key];
    delete selectedDraftByThread.current[key];
    delete desktopCollapsedByThread.current[key];
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
      if (externalThreadId && textToSend.trim() && typeof navigator !== "undefined" && navigator.clipboard) {
        navigator.clipboard.writeText(textToSend).catch(() => { });
      }
      const res = await createGmailDraft({
        to_email: effectiveEmail,
        subject: subjectToSend,
        body: textToSend,
        thread_id: externalThreadId,
        case_id: threadKey,
      });
      window.open(res.web_url, "_blank", "noopener,noreferrer");
    } catch {
      const fallbackUrl = externalThreadId
        ? `https://mail.google.com/mail/#all/${encodeURIComponent(externalThreadId)}`
        : `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(effectiveEmail)}&su=${encodeURIComponent(subjectToSend)}&body=${encodeURIComponent(textToSend)}`;
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
    setAttachments([]);
    setAttachError(null);
    setEnhanceError(null);
    setEnhanceSources([]);
    setLastEnhance(null);
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

  // Auto-open on desktop when an AI draft is waiting (unless the owner collapsed it for this thread),
  // so drafts don't stay hidden in a tiny 1-line bar at the bottom.
  useEffect(() => {
    if (initialSent) {
      setIsDesktopExpanded(false);
      return;
    }
    if (desktopCollapsedByThread.current[key]) {
      setIsDesktopExpanded(false);
      return;
    }
    const threadHasDraft = Boolean(draftText) || hasDrafts;
    setIsDesktopExpanded(threadHasDraft);
  }, [key, initialSent, hasDrafts, draftText]);

  useEffect(() => {
    if (replyingTo) {
      desktopCollapsedByThread.current[key] = false;
      setIsDesktopExpanded(true);
      desktopTextareaRef.current?.focus();
    }
  }, [replyingTo, key]);

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
    const attachmentIds = attachments.map((a) => a.attachmentId);
    forgetTyped();
    setExpandedDraftThreadKey(null);
    setIsMobileEnOpen(false);
    if (isListening) stopListening();
    if (onAcceptAndSend) {
      onAcceptAndSend(content, activeChannel, replyingTo?.id, attachmentIds);
      setAttachments([]);
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
    const attachmentIds = attachments.map((a) => a.attachmentId);
    if (isListening) stopListening();
    if (onSendManualReply) {
      onSendManualReply(content, activeChannel, replyingTo?.id, attachmentIds);
      forgetTyped();
      setAttachments([]);
      setContent("");
      if (onClearReplyingTo) {
        onClearReplyingTo();
      }
      setIsSent(true);
      setUndoSeconds(30);
    }
  };

  // State 1: AI draft available or matching draft text (only if not already sent)
  const hasDraft = !isSent && (Boolean(draftText) || Boolean(content.trim() && effectiveDrafts.length > 0));
  const isMobileDraftsOpen = hasDraft && expandedDraftThreadKey === key;
  const activeDraft = effectiveDrafts.find((d, idx) => getDraftKey(d, idx) === selectedDraftId) ?? effectiveDrafts[0];
  const activeCommitments = hasDraft ? (activeDraft?.commitments ?? []) : [];

  // Auto-grow and auto-shrink all inline reply boxes smoothly with content (Gmail-style inline sizing).
  useEffect(() => {
    const el = collapsedTextareaRef.current;
    if (!el || isMobileDraftsOpen) return;
    syncTextareaHeight(el, MOBILE_COLLAPSED_MAX_HEIGHT, shouldPinComposerEnd(el, isListening));
  }, [content, isMobileDraftsOpen, hasDraft, isListening]);

  useEffect(() => {
    const el = mobileExpandedTextareaRef.current;
    if (!el || !isMobileDraftsOpen) return;
    syncTextareaHeight(el, MOBILE_EXPANDED_MAX_HEIGHT, shouldPinComposerEnd(el, isListening));
  }, [content, isMobileDraftsOpen, hasDraft, isListening]);

  useEffect(() => {
    const el = desktopTextareaRef.current;
    if (!el || !isDesktopExpanded || isSent) return;
    const resize = () =>
      syncTextareaHeight(el, desktopComposerMaxHeight(), shouldPinComposerEnd(el, isListening));
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [content, isDesktopExpanded, isSent, hasDraft, activeChannel, isListening]);

  useEffect(() => {
    syncTextareaHeight(enhanceTextareaRef.current, 120, enhanceVoice.isListening);
  }, [enhancePrompt, enhanceVoice.isListening, isDesktopExpanded, isMobileDraftsOpen]);

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
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        aria-label="Attach file"
        onChange={(e) => void handleFilesSelected(e.target.files)}
      />
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
            {(hasDraft || content.trim()) && (
              <div className="flex justify-center items-center gap-1.5 flex-wrap">
                {hasDraft && (
                  <div className="inline-flex items-center gap-1 max-w-full px-2 py-1 rounded-full bg-[#EFF6FF] border border-[#BFDBFE]/80 shadow-[0_2px_8px_rgba(26,115,232,0.08)] text-[11.5px] overflow-x-auto">
                    <AstraIcon className="w-3.5 h-3.5 text-[#1a73e8] shrink-0 ml-1" />
                    {effectiveDrafts && effectiveDrafts.length > 0 ? (
                      <div className="flex items-center gap-0.5 shrink-0">
                        {effectiveDrafts.map((d, idx) => {
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
                      title="Open enhance bar, English translation, reject, and full editor"
                      aria-label="Draft options"
                    >
                      <SlidersHorizontal className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
                <DraftCommitments commitments={activeCommitments} />
              </div>
            )}

            {renderAttachmentChips()}

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

              {/* Unified Rounded Pill Input Pre-filled with Draft 1 + Attach + Embedded Channel Shortcut */}
              <div className="flex-1 min-w-0 flex items-end gap-1.5 bg-[#F1F5F9] border border-[#E2E8F0] focus-within:border-[#1a73e8] focus-within:bg-white rounded-[20px] pl-3.5 pr-1.5 py-1.5 transition-colors">
                <textarea
                  ref={collapsedTextareaRef}
                  rows={1}
                  value={content}
                  onChange={(e) => editContent(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (activeChannel === "gmail" ? (e.metaKey || e.ctrlKey) : !e.shiftKey)) {
                      e.preventDefault();
                      if (hasDraft) {
                        handleAccept();
                      } else {
                        handleSendNormal();
                      }
                    }
                  }}
                  placeholder={activeChannel === "gmail" ? "Type a Gmail reply..." : "Type a WhatsApp reply..."}
                  className="w-full max-h-[180px] overflow-y-auto text-[14.5px] bg-transparent text-[var(--ink)] placeholder:text-[#94A3B8] focus:outline-none resize-none leading-[1.35] py-0.5"
                />

                {(caseId || key) && (
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploadingAttachment}
                    className="w-7 h-7 rounded-full shrink-0 text-[#0F172A] hover:text-[#1a73e8] hover:bg-blue-50 flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50 mb-0.5"
                    title="Attach file (uploads to Drive & sends with reply)"
                    aria-label="Attach file"
                  >
                    {isUploadingAttachment ? <Loader2 className="w-4 h-4 animate-spin" /> : <Paperclip className="w-4 h-4 stroke-[2]" />}
                  </button>
                )}

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
          /* EXPANDED DRAFT MODE (Floating, scrollable cards for mobile) */
          <div className="flex flex-col gap-2">
            {/* Slim Top Draft Toolbar: Draft Switcher Tabs + EN / Reject / Expand / Collapse */}
            <div className="flex items-center justify-between gap-2">
              {effectiveDrafts && effectiveDrafts.length > 0 ? (
                <div className="flex items-center gap-0.5 bg-[var(--bg)] p-0.5 rounded-full border border-[var(--line)] overflow-x-auto max-w-full">
                  {effectiveDrafts.map((d, idx) => {
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

            {/* Scrollable mobile draft + English translation container */}
            <div className="max-h-[40vh] overflow-y-auto space-y-2 pr-0.5">
              {isMobileEnOpen && (
                <div className="text-[11.5px] text-[var(--ink-2)] italic bg-[var(--bg)] border border-[var(--line)] rounded-xl px-2.5 py-2 whitespace-pre-line leading-snug max-h-[120px] overflow-y-auto">
                  {mobileEnLoading && "Translating..."}
                  {mobileEnFailed && "Translation unavailable right now."}
                  {mobileEnglishText}
                </div>
              )}

              {/* Auto-growing Draft Box with Tucked Voice + NL Pill */}
              <div className="relative rounded-2xl bg-[var(--bg)] border border-[var(--line)] focus-within:border-[var(--ink)] focus-within:bg-[var(--pane)] transition-colors">
                <textarea
                  ref={mobileExpandedTextareaRef}
                  rows={4}
                  value={content}
                  onChange={(e) => editContent(e.target.value)}
                  placeholder="Edit Astra draft..."
                  className="w-full min-h-[100px] max-h-[220px] text-[15px] p-2.5 pr-18 bg-transparent text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none resize-none leading-snug"
                />
                <div className="absolute right-2 bottom-2 flex items-center gap-1">
                  {(caseId || key) && (
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploadingAttachment}
                      className="w-7 h-7 rounded-full flex items-center justify-center border bg-[var(--pane)] text-[var(--ink-2)] border-[var(--line)] hover:text-[var(--ink)] disabled:opacity-60 transition-colors cursor-pointer"
                      title="Attach file (also uploads to Google Drive)"
                      aria-label="Attach file"
                    >
                      {isUploadingAttachment ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-[#1a73e8]" />
                      ) : (
                        <Paperclip className="w-3.5 h-3.5" />
                      )}
                    </button>
                  )}
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

              {renderAttachmentChips()}

              <DraftCommitments commitments={activeCommitments} />
            </div>

            {/* Mobile Floating Enhance Prompt Bar */}
            {renderEnhanceBar(true)}

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
      {/* DESKTOP COMPOSER (Floating dock, expands smoothly on click/reply)    */}
      {/* =================================================================== */}
      {!isDesktopExpanded ? (
        <div
          className={cn(
            "hidden sm:flex shrink-0 px-4 pt-1 pb-[max(1.5rem,env(safe-area-inset-bottom))] bg-transparent select-none",
            className
          )}
        >
          <div
            className={cn(
              "w-full flex flex-col overflow-hidden rounded-[16px] border transition-all",
              hasDraft
                ? "border-[#93C5FD] bg-gradient-to-r from-[#EFF6FF] via-[var(--pane)] to-[var(--pane)] shadow-[0_12px_34px_rgba(26,115,232,0.18)] ring-1 ring-[#1a73e8]/15"
                : "border-[var(--line)] bg-[var(--pane)] shadow-[0_10px_28px_rgba(10,27,47,0.11)] hover:shadow-[0_12px_32px_rgba(10,27,47,0.14)]"
            )}
          >
            <DraftCommitments commitments={activeCommitments} />
            <div className="w-full flex items-center justify-between gap-3 px-4 py-3">
              <button
                type="button"
                onClick={() => {
                  desktopCollapsedByThread.current[key] = false;
                  setIsDesktopExpanded(true);
                  setTimeout(() => desktopTextareaRef.current?.focus(), 40);
                }}
                className="flex-1 flex items-center gap-2.5 min-w-0 text-left px-1.5 py-1 rounded-[10px] hover:bg-black/[0.03] transition-colors cursor-pointer"
              >
                {hasDraft && (
                  <span className="w-7 h-7 rounded-full bg-[#1a73e8]/12 text-[#1a73e8] inline-flex items-center justify-center shrink-0">
                    <AstraIcon className="w-4 h-4" />
                  </span>
                )}
                <span className="truncate text-[13.5px] text-[var(--ink-2)]">
                  {hasDraft ? (
                    <>
                      <strong className="font-semibold text-[#0A1B2F]">AI Draft ready ({drafts.length}):</strong>{" "}
                      <span>&ldquo;{(content || drafts[0]?.text || "").replace(/\s+/g, " ").slice(0, 110)}...&rdquo;</span>
                    </>
                  ) : (
                    t("inbox.reply_placeholder", "Click to reply...")
                  )}
                </span>
              </button>

              <div className="flex items-center gap-2 shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    desktopCollapsedByThread.current[key] = false;
                    setIsDesktopExpanded(true);
                    setTimeout(() => desktopTextareaRef.current?.focus(), 40);
                  }}
                  className="h-9 px-3 text-[12.5px] border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] rounded-[10px]"
                >
                  {hasDraft ? t("Edit") : "Reply"}
                </Button>
                {hasDraft && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleAccept}
                    className="h-9 px-3.5 text-[12.5px] font-bold rounded-[10px] shadow-xs"
                    icon={<AstraIcon className="w-3.5 h-3.5" />}
                  >
                    {t("inbox.approve_draft", "Accept & send")}
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div
          className={cn(
            "hidden sm:flex shrink-0 px-4 pt-1.5 pb-[max(1.25rem,env(safe-area-inset-bottom))] bg-transparent flex-col gap-2 select-none",
            className
          )}
        >
          {/* Floating Top Strip: Channel + Draft Switcher + Commitments Pill + Persona + Controls */}
          <div className="flex items-center justify-between gap-2 flex-wrap text-xs text-[var(--ink-3)] px-0.5">
            <div className="flex items-center gap-2 flex-wrap min-w-0">
              {/* Locked Channel Pill */}
              <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[var(--ink)] bg-[var(--pane)] border border-[var(--line)] px-2.5 py-1 rounded-full shadow-2xs shrink-0">
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

              {/* Floating AI Draft Switcher Pills */}
              {effectiveDrafts && effectiveDrafts.length > 0 && (
                <div className="flex items-center gap-0.5 bg-[var(--pane)] p-0.5 rounded-full border border-[var(--line)] shadow-2xs">
                  {effectiveDrafts.map((d, idx) => {
                    const draftKey = getDraftKey(d, idx);
                    const isSelected = selectedDraftId === draftKey;
                    const label = `Draft ${idx + 1}`;
                    return (
                      <button
                        key={`draft-${draftKey}`}
                        type="button"
                        onClick={() => selectDraft(d, idx)}
                        className={cn(
                          "px-2.5 py-0.5 rounded-full text-[11.5px] font-medium transition-colors cursor-pointer whitespace-nowrap",
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

              {/* Click-to-open floating Commitments pill */}
              <DraftCommitments commitments={activeCommitments} />
            </div>

            <div className="flex items-center gap-1.5 shrink-0">
              {effectiveDrafts && effectiveDrafts.length > 0 && draftPersona && (
                <Link
                  href="/settings?group=persona"
                  title={`Drafted using "${draftPersona.name}" (v${draftPersona.version}). Click to edit persona.`}
                  className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--ink-2)] hover:text-[var(--ink)] bg-[var(--pane)] border border-[var(--line)] px-2.5 py-1 rounded-full shadow-2xs transition-colors whitespace-nowrap"
                >
                  <UserCheck className="w-3 h-3 text-[#1a73e8] shrink-0" />
                  <span>Acting as <strong className="font-semibold text-[var(--ink)]">{draftPersona.actingAs}</strong></span>
                </Link>
              )}
              {detectedLanguage && (
                <span
                  className="text-[10.5px] font-semibold text-[var(--ink-3)] bg-[var(--pane)] border border-[var(--line)] px-2 py-1 rounded-full shadow-2xs whitespace-nowrap"
                  title={detectedLanguage}
                >
                  {detectedLanguage.toLowerCase().includes("nl") || detectedLanguage.toLowerCase().includes("dutch")
                    ? "NL"
                    : detectedLanguage.toLowerCase().includes("en")
                      ? "EN"
                      : detectedLanguage}
                </span>
              )}
              <button
                type="button"
                onClick={handleOpenFullEdit}
                className="p-1.5 rounded-full bg-[var(--pane)] border border-[var(--line)] shadow-2xs hover:bg-[var(--selected)] text-[var(--ink-3)] hover:text-[var(--ink)] cursor-pointer"
                title="Expand reply window"
                aria-label="Expand reply window"
              >
                <Maximize2 className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => {
                  desktopCollapsedByThread.current[key] = true;
                  setIsDesktopExpanded(false);
                }}
                className="p-1.5 rounded-full bg-[var(--pane)] border border-[var(--line)] shadow-2xs hover:bg-[var(--selected)] text-[var(--ink-3)] hover:text-[var(--ink)] cursor-pointer"
                title="Collapse reply box"
                aria-label="Collapse reply box"
              >
                <ChevronDown className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Floating Draft Writing + Translation Card (independently scrollable so nothing clips) */}
          <div
            onDragOver={(e) => {
              if (!caseId && !key) return;
              if (e.dataTransfer?.types?.includes("Files")) {
                e.preventDefault();
                setIsDraggingFile(true);
              }
            }}
            onDragLeave={() => setIsDraggingFile(false)}
            onDrop={(e) => {
              setIsDraggingFile(false);
              if (!caseId && !key) return;
              if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
                e.preventDefault();
                void handleFilesSelected(e.dataTransfer.files);
              }
            }}
            className={cn(
              "rounded-2xl border bg-[var(--pane)] shadow-[0_10px_30px_rgba(10,27,47,0.10)] focus-within:border-[var(--accent)] focus-within:ring-2 focus-within:ring-[var(--accent)]/15 transition-all max-h-[38vh] min-h-[112px] overflow-y-auto",
              isDraggingFile ? "border-[#1a73e8] ring-2 ring-[#1a73e8]/30 bg-[#EFF6FF]/30" : "border-[var(--line)]"
            )}
          >
            {replyingTo && (
              <div className="mx-3 mt-2.5 flex items-start justify-between gap-2 p-2 px-3 rounded-xl bg-[var(--selected)] border-l-2 border-l-[var(--accent)] border border-[var(--line)] text-xs">
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

            <textarea
              ref={desktopTextareaRef}
              rows={4}
              value={content}
              onChange={(e) => editContent(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (activeChannel === "gmail" ? (e.metaKey || e.ctrlKey) : !e.shiftKey)) {
                  e.preventDefault();
                  if (hasDraft) {
                    handleAccept();
                  } else {
                    handleSendNormal();
                  }
                }
              }}
              placeholder={
                activeChannel === "gmail"
                  ? "Type an email reply... (⌘/Ctrl+Enter to send)"
                  : t("inbox.reply_placeholder", "Type a reply... (Press Enter to send)")
              }
              className="w-full min-h-[100px] text-[13.5px] px-3.5 py-2.5 bg-transparent border-0 text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none resize-y leading-relaxed"
            />

            <div className="px-3 pb-2">
              <TranslationToggle
                text={content}
                language={
                  effectiveDrafts.find((d) => d.text.trim() === content.trim())?.language
                  ?? (effectiveDrafts.some((d) => d.language === "nl") ? "nl" : undefined)
                }
                cachedEnglish={effectiveDrafts.find((d) => d.text.trim() === content.trim())?.englishMeaning}
                cachedDutch={effectiveDrafts.find((d) => d.text.trim() === content.trim())?.dutchMeaning}
                panelClassName="max-w-full max-h-[150px] overflow-y-auto"
              />
            </div>

            {renderAttachmentChips()}
          </div>

          {/* Floating Enhance / Redraft Prompt Bar (with voice mic + NL/EN toggle) */}
          {renderEnhanceBar(false)}

          {/* Floating Bottom Utility & Action Row */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5">
            {/* Left floating utilities: Dictate + Lang + Translate to Dutch */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                type="button"
                onClick={() => toggleVoiceInput(content)}
                className={cn(
                  "px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 shrink-0 border shadow-2xs select-none",
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
                className="text-[10.5px] font-bold px-2.5 py-1 rounded-full border shadow-2xs transition-all cursor-pointer flex items-center gap-1 select-none bg-[var(--pane)] hover:bg-[var(--selected)] border-[var(--line)] text-[var(--ink-2)]"
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

              {content.trim() && (
                <button
                  type="button"
                  onClick={() => void translateContentToDutch()}
                  disabled={isTranslating}
                  className="text-[10.5px] font-bold px-2.5 py-1 rounded-full border shadow-2xs transition-all cursor-pointer flex items-center gap-1 select-none bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] hover:text-[var(--ink)] border-[var(--line)] disabled:opacity-60"
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
              {(caseId || key) && (
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploadingAttachment}
                  className="text-[10.5px] font-bold px-2.5 py-1 rounded-full border shadow-2xs transition-all cursor-pointer flex items-center gap-1 select-none bg-[var(--pane)] hover:bg-[var(--selected)] text-[var(--ink-2)] hover:text-[var(--ink)] border-[var(--line)] disabled:opacity-60"
                  title="Attach file for Gmail/WhatsApp & sync to Google Drive"
                >
                  {isUploadingAttachment ? (
                    <Loader2 className="w-3 h-3 animate-spin text-[#1a73e8]" />
                  ) : (
                    <Paperclip className="w-3 h-3" />
                  )}
                  <span>{isUploadingAttachment ? "Uploading…" : "Attach"}</span>
                </button>
              )}
            </div>

            {/* Right floating actions */}

              {/* Right actions (no redundant Edit button while already editing inline) */}
              {hasDraft ? (
                <div className="flex flex-wrap items-center gap-1.5 justify-end ml-auto">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRejectClick}
                    className="text-[var(--ink-3)] hover:text-red-600 whitespace-nowrap shrink-0 h-8 px-2.5"
                  >
                    {t("Reject")}
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
                    {t("inbox.approve_draft", "Accept & send")}
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
                    {t("Send")}
                  </Button>
                </div>
              )}
            </div>
        </div>
      )}

      {/* Expanded Pop-Out Editor (Mobile Full-Height Sheet + Desktop Gmail-style Compose Dialog) */}
      {isEditingFull && (
        <div
          className="fixed inset-0 z-50 bg-[var(--pane)] sm:bg-black/40 sm:backdrop-blur-[1px] flex flex-col sm:items-center sm:justify-center sm:p-6"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              stopListening();
              setIsEditingFull(false);
            }
          }}
        >
          <div className="flex-1 sm:flex-initial flex flex-col w-full h-full sm:max-w-3xl sm:h-[78vh] sm:max-h-[760px] bg-[var(--pane)] sm:rounded-[14px] sm:border sm:border-[var(--line)] sm:shadow-2xl overflow-hidden">
            <div className="h-14 px-4 sm:px-5 border-b border-[var(--line)] flex items-center justify-between gap-3 flex-shrink-0 bg-[var(--bg)]/50">
              <div className="min-w-0 flex items-center gap-2.5">
                <span className="font-heading font-bold text-[15px] sm:text-[16px] text-[var(--ink)] shrink-0">
                  {hasDraft ? "Edit AI Draft" : "Compose Reply"}
                </span>
                {subject && (
                  <span className="hidden sm:inline text-xs text-[var(--ink-3)] truncate">
                    · {subject}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
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
                  className="p-1.5 rounded-lg text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] cursor-pointer"
                  title="Close expanded editor"
                  aria-label="Close expanded editor"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="flex-1 p-4 sm:p-5 flex flex-col min-h-0">
              <textarea
                autoFocus
                value={fullEditText}
                onChange={(e) => setFullEditText(e.target.value)}
                className="flex-1 w-full text-base sm:text-[14.5px] leading-relaxed p-3.5 bg-[var(--bg)] border border-[var(--line)] rounded-[var(--radius-ctl)] text-[var(--ink)] focus:outline-none focus:border-[var(--ink)] resize-none overflow-y-auto"
              />
            </div>

            <div className="p-4 sm:px-5 border-t border-[var(--line)] flex gap-2 sm:justify-end pb-[max(1rem,env(safe-area-inset-bottom))]">
              <Button
                variant="ghost"
                size="default"
                className="flex-1 sm:flex-initial sm:px-5"
                onClick={() => {
                  stopListening();
                  setIsEditingFull(false);
                }}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="default"
                className="flex-1 sm:flex-initial sm:px-6 font-bold"
                onClick={handleSaveFullEdit}
              >
                Save Draft
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
