import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { chatPreview, chatTitle, listTime, roleLabel, tickFromStatus } from "@/lib/chats";
import type { ChatFilter, ChatItem } from "@/types/chats";
import { TickIcon } from "@/components/chats/TickIcon";

const FILTERS: ReadonlyArray<readonly [ChatFilter, string]> = [
  ["all", "All"],
  ["unread", "Unread"],
  ["tenants", "Tenants"],
  ["contractors", "Contractors"],
];

function initials(title: string): string {
  const parts = title.trim().split(/\s+/);
  const letters = parts.length >= 2 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : title.slice(0, 2);
  return letters.toUpperCase();
}

function ChatRow({ item, selected, onSelect }: { item: ChatItem; selected: boolean; onSelect: () => void }) {
  const title = chatTitle(item.name, item.chat_key);
  const role = roleLabel(item.person_kind);
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2.5 text-left border-b border-[var(--line)] cursor-pointer transition-colors",
        selected ? "bg-[var(--selected)]" : "bg-[var(--pane)] hover:bg-[var(--bg)]"
      )}
    >
      <div className="w-10 h-10 shrink-0 rounded-full bg-[var(--selected)] border border-[var(--line)] flex items-center justify-center text-xs font-bold text-[var(--ink-2)]">
        {initials(title)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className={cn("truncate text-[13.5px] text-[var(--ink)]", item.unread > 0 ? "font-bold" : "font-semibold")}>
            {title}
          </span>
          <span className="shrink-0 text-[11px] text-[var(--ink-3)] tabular-nums">
            {listTime(item.last_at, new Date())}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <span className="flex items-center gap-1 min-w-0 text-xs text-[var(--ink-3)]">
            {item.last_direction === "outbound" && <TickIcon tick={tickFromStatus(item.last_delivery, item.last_pending)} />}
            <span className="truncate">{chatPreview(item)}</span>
          </span>
          <span className="flex items-center gap-1.5 shrink-0">
            {role && <span className="text-[10px] uppercase tracking-tight text-[var(--ink-3)]">{role}</span>}
            {item.unread > 0 && (
              <span className="min-w-5 rounded-full bg-emerald-500 px-1.5 py-0.5 text-center text-[10.5px] font-bold leading-none text-white tabular-nums">
                {item.unread}
              </span>
            )}
          </span>
        </div>
      </div>
    </button>
  );
}

interface ChatListProps {
  items: ChatItem[] | null;
  failed: boolean;
  selectedKey: string | null;
  filter: ChatFilter;
  query: string;
  hasMore: boolean;
  onFilter: (f: ChatFilter) => void;
  onQuery: (q: string) => void;
  onSelect: (chatKey: string) => void;
  onLoadMore: () => void;
}

export function ChatList(props: ChatListProps) {
  const { items, failed, selectedKey, filter, query, hasMore } = props;
  return (
    <div className="flex flex-col h-full min-h-0 bg-[var(--pane)]">
      <div className="shrink-0 space-y-2 border-b border-[var(--line)] p-3">
        <label className="flex items-center gap-2 rounded-lg border border-[var(--line)] bg-[var(--bg)] px-2.5 py-1.5">
          <Search className="w-3.5 h-3.5 text-[var(--ink-3)]" />
          <input
            type="search"
            value={query}
            onChange={(e) => props.onQuery(e.target.value)}
            placeholder="Search name, number or message"
            aria-label="Search chats"
            className="w-full bg-transparent text-xs text-[var(--ink)] outline-hidden placeholder:text-[var(--ink-3)]"
          />
        </label>
        <div className="flex gap-1" role="tablist">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={filter === key}
              onClick={() => props.onFilter(key)}
              className={cn(
                "rounded-full px-2.5 py-1 text-[11.5px] font-medium cursor-pointer transition-colors",
                filter === key ? "bg-[var(--ink)] text-white" : "bg-[var(--bg)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {failed && (
        <div className="shrink-0 bg-rose-50 px-3 py-2 text-xs text-rose-700">Could not load chats. Retrying.</div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {items === null && !failed && <div className="p-4 text-xs text-[var(--ink-3)]">Loading chats...</div>}
        {items?.length === 0 && <div className="p-4 text-xs text-[var(--ink-3)]">No chats found.</div>}
        {items?.map((item) => (
          <ChatRow
            key={item.chat_key}
            item={item}
            selected={item.chat_key === selectedKey}
            onSelect={() => props.onSelect(item.chat_key)}
          />
        ))}
        {hasMore && (
          <button
            type="button"
            onClick={props.onLoadMore}
            className="w-full py-3 text-xs font-medium text-[var(--accent-ink)] hover:bg-[var(--bg)] cursor-pointer"
          >
            Load more chats
          </button>
        )}
      </div>
    </div>
  );
}
