import Link from "next/link";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { chatTitle, roleLabel } from "@/lib/chats";
import type { ChatThread } from "@/types/chats";

/** Name (or number), role tag and, when the chat belongs to a case, a link to it in the inbox. */
export function ChatHeader({ thread, onBack }: { thread: ChatThread; onBack: () => void }) {
  const title = chatTitle(thread.name, thread.chat_key);
  const role = roleLabel(thread.person_kind);
  return (
    <div className="flex items-center gap-2 px-3 h-14 shrink-0 border-b border-[var(--line)] bg-[var(--pane)]">
      <button
        type="button"
        onClick={onBack}
        aria-label="Back to chats"
        className="md:hidden p-1.5 -ml-1 rounded-lg text-[var(--ink-2)] hover:bg-[var(--selected)] cursor-pointer"
      >
        <ArrowLeft className="w-5 h-5" />
      </button>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="truncate text-sm font-semibold text-[var(--ink)]">{title}</span>
          {role && (
            <span className="shrink-0 rounded-full border border-[var(--line)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-tight text-[var(--ink-2)]">
              {role}
            </span>
          )}
        </div>
        {thread.name?.trim() && <div className="truncate text-[11px] text-[var(--ink-3)]">{thread.chat_key}</div>}
      </div>
      {thread.case_id && (
        <Link
          href={`/inbox?thread=${encodeURIComponent(`case-${thread.case_id}`)}`}
          className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-[var(--line)] px-2.5 py-1.5 text-xs font-medium text-[var(--ink)] hover:bg-[var(--selected)]"
        >
          Open case
          <ExternalLink className="w-3 h-3" />
        </Link>
      )}
    </div>
  );
}
