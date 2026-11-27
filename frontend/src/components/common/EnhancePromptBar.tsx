"use client";

import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, Mic, MicOff, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { FlagUK, FlagNL } from "@/components/ui/FlagIcons";
import { useVoiceInput } from "@/hooks/useVoiceInput";

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

export interface EnhancePromptBarProps {
  currentText: string;
  onEnhanced: (enhancedText: string) => void;
  onEnhanceApi: (instruction: string, currentText: string) => Promise<{ ok: boolean; enhancedText?: string; problem?: string; sourcesUsed?: string[] }>;
  placeholder?: string;
  className?: string;
  compact?: boolean;
}

export function EnhancePromptBar({
  currentText,
  onEnhanced,
  onEnhanceApi,
  placeholder = "Enhance draft (e.g. shorter, check lease, add WWS rule)...",
  className,
  compact = false,
}: EnhancePromptBarProps) {
  const [instruction, setInstruction] = useState("");
  const [isEnhancing, setIsEnhancing] = useState(false);
  const [enhanceError, setEnhanceError] = useState<string | null>(null);
  const [enhanceSources, setEnhanceSources] = useState<string[]>([]);
  const [lastEnhance, setLastEnhance] = useState<{ from: string; to: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const voice = useVoiceInput({
    onTranscript: (text: string) => {
      setInstruction(text);
      setEnhanceError(null);
    },
  });

  useEffect(() => {
    syncTextareaHeight(textareaRef.current, 120, voice.isListening);
  }, [instruction, voice.isListening]);

  const handleEnhance = async (overrideInstruction?: string) => {
    const activeInstruction = (overrideInstruction || instruction).trim();
    if (!activeInstruction || isEnhancing) return;

    if (voice.isListening) voice.stopListening();
    setIsEnhancing(true);
    setEnhanceError(null);

    try {
      const res = await onEnhanceApi(activeInstruction, currentText);
      if (res.ok && res.enhancedText) {
        setLastEnhance({ from: currentText, to: res.enhancedText });
        onEnhanced(res.enhancedText);
        setInstruction("");
        setEnhanceSources(res.sourcesUsed || []);
      } else {
        setEnhanceError(res.problem || "Could not enhance draft.");
      }
    } catch {
      setEnhanceError("Enhance request timed out or failed.");
    } finally {
      setIsEnhancing(false);
    }
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--line,#e2e8f0)] bg-[var(--bg,#f8fafc)]/80 p-2 sm:p-2.5 flex flex-col gap-1.5 transition-all focus-within:border-[var(--accent,#1a73e8)] focus-within:ring-2 focus-within:ring-[var(--accent,#1a73e8)]/15 shadow-2xs",
        className
      )}
    >
      <div className="flex items-start gap-2">
        <Sparkles className="w-3.5 h-3.5 text-[#1a73e8] mt-1 shrink-0" />
        <textarea
          ref={textareaRef}
          rows={1}
          value={instruction}
          onChange={(e) => {
            setInstruction(e.target.value);
            setEnhanceError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleEnhance();
            }
          }}
          placeholder={compact ? "Enhance draft (e.g. shorter)..." : placeholder}
          disabled={isEnhancing}
          className="w-full min-h-[24px] max-h-[120px] bg-transparent text-[12.5px] leading-snug py-0.5 text-[var(--ink,#0f172a)] placeholder:text-[var(--ink-3,#94a3b8)] focus:outline-none resize-none overflow-y-auto"
        />
      </div>

      <div className="flex items-center justify-between gap-2 flex-wrap pt-0.5">
        <div className="flex items-center gap-1 flex-wrap min-w-0">
          {!instruction.trim() && !isEnhancing && (
            <>
              {(["Shorter", "Firmer", "More polite"] as const).map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => void handleEnhance(chip)}
                  className="text-[10.5px] font-medium px-2 py-0.5 rounded-full border border-[var(--line,#e2e8f0)] bg-white dark:bg-[var(--pane,#ffffff)] hover:bg-[var(--selected,#eff6ff)] text-[var(--ink-2,#475569)] hover:text-[var(--ink,#0f172a)] cursor-pointer whitespace-nowrap shadow-2xs"
                >
                  {chip}
                </button>
              ))}
            </>
          )}
          {enhanceError && <span className="text-[11px] text-red-600 font-medium">{enhanceError}</span>}
          {!enhanceError && enhanceSources.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              <span className="text-[10.5px] text-[var(--ink-3,#94a3b8)] font-medium">Sources:</span>
              {enhanceSources.slice(0, 3).map((src) => (
                <span
                  key={src}
                  className="px-2 py-0.5 rounded-full bg-white dark:bg-[var(--pane,#ffffff)] border border-[var(--line,#e2e8f0)] text-[10px] text-[var(--ink-2,#475569)] truncate max-w-[150px]"
                  title={src}
                >
                  {src}
                </span>
              ))}
            </div>
          )}
          {lastEnhance && currentText === lastEnhance.to && (
            <button
              type="button"
              onClick={() => {
                onEnhanced(lastEnhance.from);
                setLastEnhance(null);
              }}
              className="text-[11px] text-[var(--ink-3,#94a3b8)] underline hover:text-[var(--ink,#0f172a)] cursor-pointer shrink-0 ml-1"
            >
              Undo enhance
            </button>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0 ml-auto">
          <button
            type="button"
            onClick={() => voice.toggleVoiceInput(instruction)}
            disabled={isEnhancing}
            className={cn(
              "p-1.5 rounded-full transition-all cursor-pointer shrink-0 border",
              voice.isListening
                ? "bg-cyan-500 text-black border-cyan-400 animate-pulse"
                : "bg-white dark:bg-[var(--pane,#ffffff)] border-[var(--line,#e2e8f0)] text-[var(--ink-2,#475569)] hover:text-[var(--ink,#0f172a)]"
            )}
            title={
              voice.isListening
                ? "Stop dictating instruction"
                : `Dictate instruction (${voice.speechLang === "nl" ? "Dutch" : "English"})`
            }
            aria-label="Dictate enhancement instruction"
          >
            {voice.isListening ? <MicOff className="w-3.5 h-3.5" /> : <Mic className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            onClick={() => voice.setSpeechLang((prev: "nl" | "en") => (prev === "nl" ? "en" : "nl"))}
            className="text-[10px] font-bold px-2 py-1 rounded-full border border-[var(--line,#e2e8f0)] bg-white dark:bg-[var(--pane,#ffffff)] hover:bg-[var(--selected,#eff6ff)] text-[var(--ink-2,#475569)] cursor-pointer inline-flex items-center gap-1 shrink-0"
            title="Switch instruction voice language (NL / EN)"
          >
            {voice.speechLang === "nl" ? <FlagNL className="w-3 h-2" /> : <FlagUK className="w-3 h-2" />}
            <span>{voice.speechLang === "nl" ? "NL" : "EN"}</span>
          </button>
          <button
            type="button"
            onClick={() => void handleEnhance()}
            disabled={isEnhancing || !instruction.trim()}
            className="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-[#1a73e8] text-white hover:bg-[#1557b0] disabled:opacity-45 cursor-pointer inline-flex items-center gap-1 shrink-0 shadow-2xs"
          >
            {isEnhancing ? <Loader2 className="w-3 h-3 animate-spin" /> : <ArrowRight className="w-3 h-3" />}
            <span>{isEnhancing ? "Enhancing..." : "Enhance"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
