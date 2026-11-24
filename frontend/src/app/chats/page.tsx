"use client";

import React, { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MessageCircle } from "lucide-react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { ChatList } from "@/components/chats/ChatList";
import { ChatPane } from "@/components/chats/ChatPane";
import { useLanguage } from "@/context/LanguageContext";
import { useChatList } from "@/hooks/useChatList";
import { chatKeyFromParam } from "@/lib/chats";
import { cn } from "@/lib/utils";
import type { ChatFilter } from "@/types/chats";

function ChatsView() {
  const router = useRouter();
  const { t } = useLanguage();
  const chatKey = chatKeyFromParam(useSearchParams().get("chat"));
  const [filter, setFilter] = useState<ChatFilter>("all");
  const [query, setQuery] = useState("");
  const list = useChatList(filter, query);

  const open = (key: string) => router.push(`/chats?chat=${encodeURIComponent(key)}`, { scroll: false });

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[#0A1B2F] text-[var(--ink)] font-sans antialiased">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar pageTitle={t("nav.chats", "Chats")} hideSearch />
        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <main className="flex-1 m-0 md:mr-[10px] md:mb-[10px] bg-white md:rounded-[14px] md:border md:border-[#27272a] md:shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-row overflow-hidden relative pb-14 md:pb-0">
            <div
              className={cn(
                "w-full md:w-[340px] md:min-w-[340px] shrink-0 border-r border-[var(--line)]",
                chatKey ? "hidden md:block" : "block"
              )}
            >
              <ChatList
                items={list.items}
                failed={list.failed}
                selectedKey={chatKey}
                filter={filter}
                query={query}
                hasMore={list.hasMore}
                onFilter={setFilter}
                onQuery={setQuery}
                onSelect={open}
                onLoadMore={list.loadMore}
              />
            </div>
            <div className={cn("flex-1 min-w-0 flex-col bg-[var(--bg)]", chatKey ? "flex" : "hidden md:flex")}>
              {chatKey ? (
                <ChatPane
                  key={chatKey}
                  chatKey={chatKey}
                  onBack={() => router.push("/chats", { scroll: false })}
                  onRead={list.refresh}
                />
              ) : (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 text-[var(--ink-3)]">
                  <MessageCircle className="w-8 h-8" strokeWidth={1.5} />
                  <span className="text-sm">Select a chat to read it</span>
                </div>
              )}
            </div>
          </main>
        </div>
      </div>
      <MobileTabBar />
    </div>
  );
}

export default function ChatsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-zinc-400">Loading chats...</div>}>
      <ChatsView />
    </Suspense>
  );
}
