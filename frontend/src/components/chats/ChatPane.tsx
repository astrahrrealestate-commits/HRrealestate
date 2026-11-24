"use client";

import { useEffect, useRef } from "react";
import { markChatRead } from "@/lib/chatsApi";
import { notifyChatsChanged } from "@/hooks/useChatUnread";
import { useChatThread } from "@/hooks/useChatThread";
import { ChatHeader } from "@/components/chats/ChatHeader";
import { ChatThread } from "@/components/chats/ChatThread";

interface ChatPaneProps {
  chatKey: string;
  onBack: () => void;
  onRead: () => void;
}

/** The open chat. Mount with `key={chatKey}` so switching chats starts clean. Opening it, and every newer message
 * that arrives while it is open, marks it read. */
export function ChatPane({ chatKey, onBack, onRead }: ChatPaneProps) {
  const { thread, messages, failed, hasOlder, loadingOlder, loadOlder } = useChatThread(chatKey);
  const newestId = messages[messages.length - 1]?.id;
  const onReadRef = useRef(onRead);
  useEffect(() => {
    onReadRef.current = onRead;
  });

  // Only a new chat or a new newest message marks it read: a filter click or a keystroke in the search box changes
  // `onRead` but must not post again.
  useEffect(() => {
    if (!newestId) return;
    void markChatRead(chatKey).then((ok) => {
      if (!ok) return;
      onReadRef.current();
      notifyChatsChanged();
    });
  }, [chatKey, newestId]);

  if (!thread) {
    return (
      <div className="flex flex-1 flex-col min-h-0">
        <div className="md:hidden p-2">
          <button type="button" onClick={onBack} className="text-sm text-[var(--accent-ink)] cursor-pointer">
            Back to chats
          </button>
        </div>
        <div className="p-6 text-sm text-[var(--ink-3)]">
          {failed ? "Could not load this chat." : "Loading messages..."}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-1 flex-col min-h-0 min-w-0">
      <ChatHeader thread={thread} onBack={onBack} />
      {failed && (
        <div className="shrink-0 bg-rose-50 px-3 py-1.5 text-xs text-rose-700">
          Connection problem. Showing the last messages loaded.
        </div>
      )}
      <ChatThread messages={messages} hasOlder={hasOlder} loadingOlder={loadingOlder} onLoadOlder={loadOlder} />
    </div>
  );
}
