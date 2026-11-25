"use client";

import React, { useState, useMemo, useRef, useCallback } from "react";
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
  bodyHtml?: string | null;
  className?: string;
  isOwner?: boolean;
}

function wrapEmailSrcDoc(htmlContent: string): string {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:;" />
<base target="_blank" />
<style>
  html, body {
    margin: 0;
    padding: 0;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13.5px;
    line-height: 1.55;
    color: #111827;
    background: transparent;
    overflow-wrap: anywhere;
  }
  img { max-width: 100%; height: auto; }
  table { max-width: 100% !important; height: auto !important; }
  pre, code { white-space: pre-wrap; word-break: break-word; }
  a { color: #1a73e8; }
</style>
</head>
<body>${htmlContent}</body>
</html>`;
}

function SandboxedHtmlBody({ htmlContent }: { htmlContent: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [frameHeight, setFrameHeight] = useState<number>(160);
  const srcDoc = useMemo(() => wrapEmailSrcDoc(htmlContent), [htmlContent]);

  const measureHeight = useCallback(() => {
    const el = iframeRef.current;
    const doc = el?.contentDocument;
    if (!doc) return;
    const bodyHeight = doc.body?.scrollHeight || 0;
    const docHeight = doc.documentElement?.scrollHeight || 0;
    const next = Math.max(40, Math.min(Math.max(bodyHeight, docHeight) + 8, 2400));
    setFrameHeight(next);
  }, []);

  return (
    <div className="w-full overflow-x-auto">
      <iframe
        ref={iframeRef}
        title="Email message content"
        srcDoc={srcDoc}
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        onLoad={measureHeight}
        style={{ height: `${frameHeight}px` }}
        className="w-full min-w-[260px] border-0 bg-transparent block"
      />
    </div>
  );
}

const URL_REGEX = /(https?:\/\/[^\s<>()]+)/g;

function renderLinkifiedText(text: string, isOwner: boolean): React.ReactNode {
  if (!text) return null;
  const parts = text.split(URL_REGEX);
  return parts.map((part, idx) => {
    if (!part.startsWith("http://") && !part.startsWith("https://")) {
      return <React.Fragment key={idx}>{part}</React.Fragment>;
    }
    let cleanUrl = part;
    let trailing = "";
    while (cleanUrl.length > 0 && /[.,;:!?\])>'"]$/.test(cleanUrl)) {
      trailing = cleanUrl.slice(-1) + trailing;
      cleanUrl = cleanUrl.slice(0, -1);
    }
    if (!cleanUrl) return <React.Fragment key={idx}>{part}</React.Fragment>;
    return (
      <React.Fragment key={idx}>
        <a
          href={cleanUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "underline break-all transition-opacity hover:opacity-80",
            isOwner ? "text-white sm:text-[#1a73e8]" : "text-[#1a73e8]"
          )}
        >
          {cleanUrl}
        </a>
        {trailing}
      </React.Fragment>
    );
  });
}

export function ExpandableMessageBody({
  body,
  bodyHtml,
  className = "text-[13.5px] leading-relaxed whitespace-pre-line select-text [overflow-wrap:anywhere]",
  isOwner = false,
}: ExpandableMessageBodyProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { cleanBody, quotedText } = useMemo(() => parseQuotedText(body), [body]);
  const [showPlainText, setShowPlainText] = useState(false);

  if (bodyHtml && !showPlainText) {
    return (
      <div className="space-y-2 min-w-0">
        <SandboxedHtmlBody htmlContent={bodyHtml} />
        {cleanBody && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setShowPlainText(true);
            }}
            className="text-[11px] text-[var(--ink-3)] hover:text-[var(--ink)] underline cursor-pointer"
          >
            View plain text
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-1.5 min-w-0">
      {bodyHtml && showPlainText && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setShowPlainText(false);
          }}
          className="text-[11px] text-[var(--ink-3)] hover:text-[var(--ink)] underline cursor-pointer"
        >
          View formatted email
        </button>
      )}
      <p className={cn(className, "[overflow-wrap:anywhere]")}>
        {renderLinkifiedText(cleanBody, isOwner)}
      </p>

      {quotedText && (
        <div className="pt-0.5 min-w-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            className={cn(
              "inline-flex items-center justify-center h-4 px-1.5 rounded text-[11px] font-bold leading-none tracking-wider transition-all cursor-pointer",
              isOwner
                ? "bg-white/20 hover:bg-white/30 text-white sm:bg-[var(--line)] sm:text-[var(--ink-2)]"
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
                "mt-2 pl-3 py-0.5 border-l-2 text-[12px] font-normal whitespace-pre-line select-text opacity-85 leading-normal [overflow-wrap:anywhere]",
                isOwner
                  ? "border-white/40 text-white/90 sm:border-[var(--line)] sm:text-[var(--ink-2)]"
                  : "border-[var(--line)] text-[var(--ink-2)]"
              )}
            >
              {renderLinkifiedText(quotedText, isOwner)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
