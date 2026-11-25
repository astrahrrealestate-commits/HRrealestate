"use client";

import React, { useState, useMemo } from "react";
import { cn } from "@/lib/utils";

export interface ParsedMessageText {
  cleanBody: string;
  quotedText: string | null;
}

/**
 * Splits raw message text into primary reply vs. collapsed quote chain.
 * Matches standard Gmail/Outlook quote headers in English, Dutch, Polish, etc.
 */
export function parseQuotedText(raw: string | null | undefined): ParsedMessageText {
  if (!raw) return { cleanBody: "", quotedText: null };
  const text = String(raw).replace(/^["']|["']$/g, "").trim();

  // Common email quote header patterns:
  // - "On ... wrote:"
  // - "Op ... schreef:" / "schreef op ...:"
  // - "... użytkownik ... napisał:"
  // - "-----Original Message-----" / "-----Oorspronkelijk bericht-----"
  // - "From: ... Sent: ... To: ..." / "Van: ... Verzonden: ... Aan: ..."
  const headerPatterns = [
    /(?:\r?\n)+(?:On\s+[^\n]+?\bwrote:\s*)/i,
    /(?:\r?\n)+(?:Op\s+[^\n]+?\bschreef[^\n]*:?\s*)/i,
    /(?:\r?\n)+(?:[^\n]+?\bużytkownik\s+[^\n]+?\bnapisał:\s*)/i,
    /(?:\r?\n)+(?:-----Original Message-----[\s\S]*)/i,
    /(?:\r?\n)+(?:-----Oorspronkelijk bericht-----[\s\S]*)/i,
    /(?:\r?\n)+(?:From:\s*[^\n]+\nSent:\s*[^\n]+)/i,
    /(?:\r?\n)+(?:Van:\s*[^\n]+\nVerzonden:\s*[^\n]+)/i,
  ];

  for (const pattern of headerPatterns) {
    const match = text.search(pattern);
    if (match > 0) {
      const cleanBody = text.slice(0, match).trimEnd();
      const quotedText = text.slice(match).trim();
      if (cleanBody) {
        return { cleanBody, quotedText };
      }
    }
  }

  // Fallback: Check for line blocks starting with '>'
  const lines = text.split("\n");
  const firstQuoteLine = lines.findIndex((l) => l.trimStart().startsWith(">"));
  if (firstQuoteLine > 0) {
    const cleanBody = lines.slice(0, firstQuoteLine).join("\n").trimEnd();
    const quotedText = lines.slice(firstQuoteLine).join("\n").trim();
    if (cleanBody) {
      return { cleanBody, quotedText };
    }
  }

  return { cleanBody: text, quotedText: null };
}

interface ExpandableMessageBodyProps {
  body: string | null | undefined;
  className?: string;
  isOwner?: boolean;
}

export function ExpandableMessageBody({
  body,
  className = "text-[13.5px] leading-relaxed whitespace-pre-line select-text",
  isOwner = false,
}: ExpandableMessageBodyProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { cleanBody, quotedText } = useMemo(() => parseQuotedText(body), [body]);

  return (
    <div className="space-y-1.5">
      <p className={className}>{cleanBody}</p>

      {quotedText && (
        <div className="pt-0.5">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            className={cn(
              "inline-flex items-center justify-center h-4 px-1.5 rounded text-[11px] font-bold leading-none tracking-wider transition-all cursor-pointer",
              isOwner
                ? "bg-white/20 hover:bg-white/30 text-white"
                : "bg-[var(--line)] hover:bg-[var(--line)]/80 text-[var(--ink-2)]"
            )}
            title={isExpanded ? "Hide trimmed text" : "Show trimmed text"}
            aria-label={isExpanded ? "Hide trimmed text" : "Show trimmed content"}
            aria-expanded={isExpanded}
          >
            ···
          </button>

          {isExpanded && (
            <div
              className={cn(
                "mt-2 pl-3 py-0.5 border-l-2 text-[12px] font-normal whitespace-pre-line select-text opacity-85 leading-normal",
                isOwner
                  ? "border-white/40 text-white/90"
                  : "border-[var(--line)] text-[var(--ink-2)]"
              )}
            >
              {quotedText}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
