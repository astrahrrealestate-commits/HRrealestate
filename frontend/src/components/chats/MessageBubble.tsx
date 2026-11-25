import { AlertTriangle, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock } from "@/lib/clock";
import { isInlineImage, isSafeMediaUrl, tickFor } from "@/lib/chats";
import type { ChatAttachment, ChatMessage } from "@/types/chats";
import { TickIcon } from "@/components/chats/TickIcon";

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Attachment({ a }: { a: ChatAttachment }) {
  const label = a.filename || "Attachment";
  if (!isSafeMediaUrl(a.url)) {
    return <div className="text-xs text-[var(--ink-3)]">{label} (unavailable)</div>;
  }
  if (isInlineImage(a.mime_type)) {
    return (
      <a href={a.url} target="_blank" rel="noopener noreferrer">
        {/* eslint-disable-next-line @next/next/no-img-element -- presigned storage URL, not an optimisable asset */}
        <img src={a.url} alt={label} loading="lazy" className="max-h-72 max-w-full rounded-lg object-cover" />
      </a>
    );
  }
  if (a.mime_type.startsWith("audio/")) {
    return <audio controls preload="none" src={a.url} className="max-w-full" />;
  }
  return (
    <a
      href={a.url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-white/70 px-2.5 py-2 text-xs text-[var(--ink)] hover:bg-white"
    >
      <FileText className="w-4 h-4 shrink-0 text-[var(--ink-3)]" />
      <span className="truncate">{label}</span>
      <span className="shrink-0 text-[var(--ink-3)]">{formatSize(a.size_bytes)}</span>
    </a>
  );
}

/** One chat bubble. The body is only ever a React text child: no HTML, no auto-linking. */
export function MessageBubble({ message: m }: { message: ChatMessage }) {
  const outbound = m.direction === "outbound";
  const hasAudio = m.attachments.some((a) => a.mime_type.startsWith("audio/"));
  return (
    <div className={cn("flex", outbound ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] md:max-w-[65%] rounded-xl px-3 py-2 shadow-xs border space-y-1.5",
          outbound ? "bg-[#d9fdd3] border-[#c5ebbd] rounded-tr-sm" : "bg-white border-[var(--line)] rounded-tl-sm"
        )}
      >
        {m.suspicious && (
          <div className="flex items-start gap-1.5 rounded-md bg-amber-50 border border-amber-200 px-2 py-1 text-[11px] text-amber-800">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
            <span>Flagged as suspicious{m.suspicious_reason ? `: ${m.suspicious_reason}` : ""}</span>
          </div>
        )}
        {m.reply_to && (
          <div className="border-l-4 border-[var(--accent)] bg-black/5 rounded-sm px-2 py-1 text-xs text-[var(--ink-2)] line-clamp-3 whitespace-pre-wrap break-words">
            {m.reply_to.text}
          </div>
        )}
        {m.attachments.map((a) => (
          <Attachment key={a.id} a={a} />
        ))}
        {m.text && (
          <div>
            {hasAudio && (
              <div className="text-[10px] uppercase tracking-wide text-[var(--ink-3)]">Transcript</div>
            )}
            <p className="text-[13.5px] leading-snug text-[var(--ink)] whitespace-pre-wrap break-words">{m.text}</p>
          </div>
        )}
        <div className="flex items-center justify-end gap-1 text-[10.5px] text-[var(--ink-3)]">
          <span className="tabular-nums">{formatClock(new Date(m.sent_at))}</span>
          {outbound && <TickIcon tick={tickFor(m)} />}
        </div>
        {outbound && m.delivery_status === "failed" && m.error && (
          <div className="text-[11px] text-rose-600 break-words">{m.error}</div>
        )}
      </div>
    </div>
  );
}
