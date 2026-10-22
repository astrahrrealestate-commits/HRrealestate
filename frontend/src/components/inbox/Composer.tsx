"use client";

import React, { useState, useEffect, useRef } from "react";
import { Sparkles, Check, RotateCcw, Send, MessageSquare, Mail, Maximize2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { DraftOption } from "@/types/dashboard";

export interface ComposerProps {
  draftText?: string;
  drafts?: DraftOption[];
  detectedLanguage?: string;
  channel?: "whatsapp" | "gmail" | string;
  onAcceptAndSend?: (text: string, channel: string) => void;
  onReject?: () => void;
  onSendManualReply?: (text: string, channel: string) => void;
  onUndo?: () => void;
  isSent?: boolean;
  sentTimestamp?: string;
  className?: string;
}

/**
 * Composer implements Sections 5.2, 5.6, 5.6.1 & 6.2:
 * - Sticky at the bottom of the conversation, never scrolls away.
 * - State 1: AI draft ready with editable textarea, draft switcher tabs, Reject, Edit, Accept and send.
 * - State 2: Sent state ("✓ Sent via WhatsApp · 08:21 · Undo" for 30s).
 * - State 3: Normal reply input with channel switch and "Draft with AI".
 * - Mobile responsive: 16px font (no iOS zoom), full-height edit sheet, mobile button stack.
 */
export function Composer({
  draftText = "",
  drafts = [],
  detectedLanguage = "Dutch (detected)",
  channel = "whatsapp",
  onAcceptAndSend,
  onReject,
  onSendManualReply,
  onUndo,
  isSent: initialSent = false,
  sentTimestamp,
  className,
}: ComposerProps) {
  const [content, setContent] = useState(draftText);
  const [selectedDraftId, setSelectedDraftId] = useState<string>(drafts[0]?.id || "d1");
  const [activeChannel, setActiveChannel] = useState<string>(channel);
  const [isEditingFull, setIsEditingFull] = useState(false);
  const [fullEditText, setFullEditText] = useState("");
  const [isSent, setIsSent] = useState(initialSent);
  const [undoSeconds, setUndoSeconds] = useState(30);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Sync draft prop changes
  useEffect(() => {
    setContent(draftText);
    setActiveChannel(channel);
    if (drafts.length > 0) {
      setSelectedDraftId(drafts[0].id);
    }
  }, [draftText, channel, drafts]);

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
      onAcceptAndSend(content, activeChannel);
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
      onSendManualReply(content, activeChannel);
      setContent("");
      setIsSent(true);
      setUndoSeconds(30);
    }
  };

  // State 1: AI draft available
  const hasDraft = Boolean(draftText);

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

  return (
    <>
      <div
        className={cn(
          "shrink-0 border-t border-[var(--line)] bg-[var(--pane)] p-3 sm:p-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] flex flex-col gap-2.5 select-none",
          className
        )}
      >
        {/* Draft Header Line with Alternative Draft Tabs */}
        {hasDraft ? (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-[var(--ink-3)]">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center gap-1.5 font-medium text-[var(--ink-2)]">
                <Sparkles className="w-3.5 h-3.5 text-[var(--accent)]" />
                <span>AI draft · {detectedLanguage}</span>
              </span>
              <span className="text-[var(--line)]">|</span>
              <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--ink-2)] bg-[var(--selected)] border border-[var(--line)] px-2 py-0.5 rounded-sm">
                {activeChannel === "gmail" ? (
                  <>
                    <Mail className="w-3 h-3 text-[var(--ink-3)]" />
                    <span>Gmail</span>
                  </>
                ) : (
                  <>
                    <MessageSquare className="w-3 h-3 text-emerald-600" />
                    <span>WhatsApp</span>
                  </>
                )}
              </span>

              {/* Draft Switcher Tabs if multiple drafts available */}
              {drafts && drafts.length > 1 && (
                <div className="flex items-center gap-1 ml-2 bg-[var(--bg)] p-0.5 rounded-[var(--radius-ctl)] border border-[var(--line)]">
                  {drafts.map((d, idx) => (
                    <button
                      key={d.id || `draft-${idx}`}
                      type="button"
                      onClick={() => {
                        setSelectedDraftId(d.id || `d${idx + 1}`);
                        setContent(d.text);
                      }}
                      className={cn(
                        "px-2 py-0.5 rounded text-[11px] transition-colors cursor-pointer",
                        selectedDraftId === (d.id || `d${idx + 1}`)
                          ? "bg-[var(--pane)] text-[var(--ink)] font-semibold shadow-2xs border border-[var(--line)]"
                          : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                      )}
                    >
                      {d.label ? (d.label.includes("Draft 1") ? "Draft 1" : d.label.includes("Draft 2") ? "Draft 2" : `Draft ${idx + 1}`) : `Draft ${idx + 1}`}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Mobile Expand Button */}
            <button
              type="button"
              onClick={handleOpenFullEdit}
              className="md:hidden inline-flex items-center gap-1 text-[var(--ink-3)] hover:text-[var(--ink)] self-end sm:self-auto"
              title="Expand full screen editor"
            >
              <Maximize2 className="w-3 h-3" />
              <span>Expand</span>
            </button>
          </div>
        ) : (
          /* Normal Reply Header: Channel switch */
          <div className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1 bg-[var(--bg)] p-0.5 rounded-[var(--radius-ctl)] border border-[var(--line)]">
              <button
                type="button"
                onClick={() => setActiveChannel("whatsapp")}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors",
                  activeChannel === "whatsapp"
                    ? "bg-[var(--pane)] text-[var(--ink)] font-semibold shadow-2xs"
                    : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                )}
              >
                <MessageSquare className="w-3 h-3 text-emerald-600" />
                <span>WhatsApp</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveChannel("gmail")}
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs transition-colors",
                  activeChannel === "gmail"
                    ? "bg-[var(--pane)] text-[var(--ink)] font-semibold shadow-2xs"
                    : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                )}
              >
                <Mail className="w-3 h-3 text-[var(--ink-3)]" />
                <span>Gmail</span>
              </button>
            </div>

            <button
              type="button"
              onClick={() => setContent(draftText || "Hi, we received your message and will arrange an inspection today.")}
              className="text-xs text-[var(--ink-2)] hover:text-[var(--accent-ink)] inline-flex items-center gap-1"
            >
              <Sparkles className="w-3 h-3 text-[var(--accent)]" />
              <span>Draft with AI</span>
            </button>
          </div>
        )}

        {/* Text Area (Enlarged size for comfortable reading and editing) */}
        <div className="relative">
          <textarea
            ref={textareaRef}
            rows={hasDraft ? 5 : 3}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Reply..."
            className="w-full min-h-[96px] sm:min-h-[110px] text-base sm:text-[14px] p-3 rounded-[var(--radius-ctl)] bg-[var(--bg)] border border-[var(--line)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:bg-[var(--pane)] focus:border-[var(--ink)] focus:outline-none transition-colors resize-y leading-relaxed"
          />
        </div>

        {/* Bottom Bar: Action proposal & Buttons */}
        {hasDraft ? (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-0.5">
            <span className="text-[11.5px] text-[var(--ink-3)] truncate hidden sm:inline">
              On accept: escalate · dispatch approved contractor · reply · log
            </span>

            {/* Desktop: Reject | Edit | Accept and send */}
            <div className="hidden sm:flex items-center gap-2 justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={onReject}
                className="text-[var(--ink-3)] hover:text-[var(--ink)]"
              >
                Reject
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => textareaRef.current?.focus()}
              >
                Edit
              </Button>
              <Button
                variant="primary"
                size="default"
                onClick={handleAccept}
                icon={<Sparkles className="w-4 h-4 fill-[#0A0A0A]" />}
              >
                Accept and send
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
          <div className="flex items-center justify-end gap-2">
            <Button
              variant="secondary"
              size="default"
              onClick={handleSendNormal}
              disabled={!content.trim()}
              icon={<Send className="w-3.5 h-3.5" />}
            >
              Send
            </Button>
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
