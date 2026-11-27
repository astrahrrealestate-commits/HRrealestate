"use client";

import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { translateText } from "@/lib/api";
import { useLanguage } from "@/context/LanguageContext";
import { cn } from "@/lib/utils";

interface TranslationToggleProps {
  /** The source text. May change while the toggle is open (an edited draft). */
  text: string;
  /** What the server said about the text; the toggle shows when it differs from the UI language. */
  language?: "nl" | "en" | "unknown";
  /** English already cached on the server for a Dutch text, so opening it costs nothing. */
  cachedEnglish?: string;
  /** Dutch already cached on the server for an English text. */
  cachedDutch?: string;
  align?: "left" | "right";
  panelClassName?: string;
}

/**
 * Translation for one chat text, into the language the dashboard is set to: Dutch messages get English when the UI
 * is English, English messages get Dutch when the UI is Dutch. Translates on the first open only; the server caches
 * it for everyone. A cached translation opens expanded, so a translated thread reads translated without clicks.
 * Results are kept per text, so editing a draft never shows the translation of an older version.
 */
export function TranslationToggle({
  text,
  language,
  cachedEnglish,
  cachedDutch,
  align = "left",
  panelClassName,
}: TranslationToggleProps) {
  const { language: uiLanguage } = useLanguage();
  const target: "en" | "nl" = uiLanguage === "nl" ? "nl" : "en";
  const source = target === "en" ? "nl" : "en";
  const cached = target === "en" ? cachedEnglish : cachedDutch;

  const [open, setOpen] = useState(Boolean(cached));
  const [results, setResults] = useState<Record<string, string | null>>({}); // text|target -> translation; null = failed
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const closedByUserRef = useRef(false);

  // A cached translation that arrives on a later refetch opens too, unless the reader closed this toggle.
  useEffect(() => {
    if (cached && !closedByUserRef.current) setOpen(true);
  }, [cached]);

  if (language !== source && !cached) return null;

  const key = `${target}|${text}`;
  const translated = cached ?? results[key];
  const loading = loadingKey === key;
  const failed = !loading && !translated && key in results;
  const dutchUi = target === "nl";

  const translate = async () => {
    setLoadingKey(key);
    const result = await translateText(text, target);
    setResults((prev) => ({ ...prev, [key]: result?.text ?? null }));
    setLoadingKey((current) => (current === key ? null : current));
  };

  const toggle = () => {
    const next = !open;
    closedByUserRef.current = !next;
    setOpen(next);
    if (next && !translated && !loading) void translate();
  };

  const showLabel = dutchUi ? "Toon Nederlandse vertaling" : "Show English translation";
  const hideLabel = dutchUi ? "Verberg Nederlands" : "Hide English";

  return (
    <div className={align === "right" ? "pr-2" : "pl-2"}>
      <button
        type="button"
        onClick={toggle}
        className="inline-flex items-center gap-1 text-xs text-[var(--ink-3)] hover:text-[var(--ink)] transition-colors cursor-pointer"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span>{open ? hideLabel : showLabel}</span>
      </button>
      {open && (
        <div
          className={cn(
            "mt-1 text-xs text-[var(--ink-3)] italic bg-[var(--pane)] border border-[var(--line)]/60 rounded px-2.5 py-1.5 max-w-[85%] whitespace-pre-line",
            align === "right" && "text-right",
            panelClassName
          )}
        >
          {loading && (dutchUi ? "Vertalen…" : "Translating…")}
          {failed && (dutchUi ? "Vertaling is nu niet beschikbaar." : "Translation is not available right now.")}
          {translated}
          {!loading && !translated && !failed && (
            <button type="button" onClick={() => void translate()} className="not-italic underline cursor-pointer">
              {dutchUi ? "Vertaal de huidige tekst" : "Translate the current text"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
