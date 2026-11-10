"use client";

import React, { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { translateToEnglish } from "@/lib/api";
import { cn } from "@/lib/utils";

interface EnglishToggleProps {
  /** The Dutch text. May change while the toggle is open (an edited draft). */
  text: string;
  /** What the server said about the text; the toggle only shows for Dutch (or when English is already cached). */
  language?: "nl" | "en" | "unknown";
  /** English already cached on the server, so opening it costs nothing. */
  cachedEnglish?: string;
  align?: "left" | "right";
}

/**
 * "Show English translation" for one text. Translates on the first open only; the server caches it for everyone.
 * Results are kept per text, so editing a draft never shows the English of an older version.
 */
export function EnglishToggle({ text, language, cachedEnglish, align = "left" }: EnglishToggleProps) {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<Record<string, string | null>>({}); // text -> English; null = failed
  const [loadingText, setLoadingText] = useState<string | null>(null);

  if (language !== "nl" && !cachedEnglish) return null;

  const english = cachedEnglish ?? results[text];
  const loading = loadingText === text;
  const failed = !loading && !english && text in results;

  const translate = async () => {
    setLoadingText(text);
    const result = await translateToEnglish(text);
    setResults((prev) => ({ ...prev, [text]: result?.textEn ?? null }));
    setLoadingText((current) => (current === text ? null : current));
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !english && !loading) void translate();
  };

  return (
    <div className={align === "right" ? "pr-2" : "pl-2"}>
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center gap-1 text-xs text-[var(--ink-3)] hover:text-[var(--ink)] transition-colors cursor-pointer"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span>{open ? "Hide English" : "Show English translation"}</span>
      </button>
      {open && (
        <div
          className={cn(
            "mt-1 text-xs text-[var(--ink-3)] italic bg-[var(--pane)] border border-[var(--line)]/60 rounded px-2.5 py-1.5 max-w-[85%] whitespace-pre-line",
            align === "right" && "text-right"
          )}
        >
          {loading && "Translating…"}
          {failed && "Translation is not available right now."}
          {english}
          {!loading && !english && !failed && (
            <button type="button" onClick={() => void translate()} className="not-italic underline cursor-pointer">
              Translate the current text
            </button>
          )}
        </div>
      )}
    </div>
  );
}
