"use client";

import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { prewarmAgentPage, AssistantCard, ConversationSummaryItem, getAgentConversations, getConversationDetail, updateAgentConversation, PreviewCardData } from "@/lib/api";

export interface AssistantAction {
  label: string;
  isPrimary?: boolean;
  actionType: string;
  payload?: any;
}

export interface AssistantMessage {
  id: string;
  sender: "user" | "assistant";
  timestamp: string;
  text: string;
  readSource?: string;
  facts?: Array<{ label: string; value: string; isAlert?: boolean }>;
  draftBlock?: {
    channel: "whatsapp" | "gmail";
    to: string;
    body: string;
  };
  steps?: string[];
  previewCard?: PreviewCardData | null;
  previewCards?: PreviewCardData[];
  cards?: AssistantCard[];
  debugInfo?: {
    pipeline_stage: string;
    fallback_reason?: string | null;
  } | null;
  actions?: AssistantAction[];
  suggestedPrompts?: string[];
}

export interface ActiveDrawerInfo {
  title: string;
  kind: "Ticket" | "Invoice" | "Thread" | string;
}

interface SuperAgentContextType {
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  toggleOpen: () => void;
  currentPageName: string;
  setCurrentPageName: (name: string) => void;
  selectedContext: string;
  setSelectedContext: (ctx: string) => void;
  panelMode: "center" | "docked";
  setPanelMode: (mode: "center" | "docked") => void;
  togglePanelMode: () => void;
  messages: AssistantMessage[];
  setMessages: React.Dispatch<React.SetStateAction<AssistantMessage[]>>;
  clearMessages: () => void;
  activeDrawerInfo: ActiveDrawerInfo | null;
  setActiveDrawerInfo: (info: ActiveDrawerInfo | null) => void;
  currentConversationId: string | null;
  setCurrentConversationId: (id: string | null) => void;
  conversationTitle: string;
  setConversationTitle: (title: string) => void;
  conversations: ConversationSummaryItem[];
  refreshConversations: () => Promise<void>;
  isHistoryOpen: boolean;
  setIsHistoryOpen: (open: boolean) => void;
  toggleHistoryOpen: () => void;
  startNewChat: () => void;
  selectConversation: (id: string) => Promise<void>;
  isLoadingConversation: boolean;
}

const SuperAgentContext = createContext<SuperAgentContextType | null>(null);

const STORAGE_KEY = "estateos_superagent_open";
const MESSAGES_KEY = "estateos_superagent_messages";
const MODE_KEY = "estateos_superagent_mode";

const DEFAULT_INITIAL_MESSAGE: AssistantMessage = {
  id: "initial-msg",
  sender: "assistant",
  timestamp: "Just now",
  text: `I know your queue, portfolio, and financial logs. Ask me to explain an item, find a document, check tenant arrears, or pick what to do first.`,
  actions: [
    {
      label: "What should I do first?",
      actionType: "query",
      payload: "What should I do first?",
      isPrimary: true,
    },
  ],
};

export function SuperAgentProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpenState] = useState<boolean>(false);
  const [panelMode, setPanelModeState] = useState<"center" | "docked">("center");
  const [currentPageName, setCurrentPageName] = useState<string>("Today");
  const [selectedContext, setSelectedContext] = useState<string>("The whole page");
  const [messages, setMessages] = useState<AssistantMessage[]>([DEFAULT_INITIAL_MESSAGE]);
  const [activeDrawerInfo, setActiveDrawerInfo] = useState<ActiveDrawerInfo | null>(null);
  const [currentConversationId, setCurrentConversationIdState] = useState<string | null>(null);
  const [conversationTitle, setConversationTitle] = useState<string>("New Chat");
  const [conversations, setConversations] = useState<ConversationSummaryItem[]>([]);
  const [isHistoryOpen, setIsHistoryOpen] = useState<boolean>(false);
  const [isLoadingConversation, setIsLoadingConversation] = useState<boolean>(false);
  const isInitialized = useRef<boolean>(false);

  const setCurrentConversationId = (id: string | null) => {
    setCurrentConversationIdState(id);
    if (id) {
      try { localStorage.setItem("estateos_superagent_conv_id", id); } catch {}
    } else {
      try { localStorage.removeItem("estateos_superagent_conv_id"); } catch {}
    }
  };

  const refreshConversations = async () => {
    const list = await getAgentConversations();
    setConversations(list);
  };

  const startNewChat = () => {
    setCurrentConversationId(null);
    setConversationTitle("New Chat");
    setMessages([DEFAULT_INITIAL_MESSAGE]);
    setIsHistoryOpen(false);
  };

  const selectConversation = async (id: string) => {
    setIsLoadingConversation(true);
    try {
      const detail = await getConversationDetail(id);
      if (detail) {
        setCurrentConversationId(detail.id);
        setConversationTitle(detail.title || "Conversation");
        if (detail.turns && detail.turns.length > 0) {
          const parsedMsgs: AssistantMessage[] = detail.turns.map((t) => ({
            id: t.id,
            sender: t.sender,
            timestamp: t.timestamp || "Just now",
            text: t.text,
            steps: t.steps,
            previewCard: t.previewCard,
            previewCards:
              t.previewCards && t.previewCards.length > 0
                ? t.previewCards
                : t.previewCard
                  ? [t.previewCard]
                  : [],
            cards: t.cards,
            actions: t.actions as any,
            suggestedPrompts: t.suggestedPrompts,
          }));
          setMessages(parsedMsgs);
        } else {
          setMessages([DEFAULT_INITIAL_MESSAGE]);
        }
      } else {
        setCurrentConversationId(null);
      }
    } finally {
      setIsLoadingConversation(false);
      setIsHistoryOpen(false);
    }
  };

  const toggleHistoryOpen = () => {
    setIsHistoryOpen((prev) => !prev);
  };

  // Load persistent open state, mode & messages across page navigations
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "true") {
        setIsOpenState(true);
      }
      const storedMode = localStorage.getItem(MODE_KEY);
      if (storedMode === "docked" || storedMode === "center") {
        setPanelModeState(storedMode);
      } else {
        setPanelModeState("center");
      }
      const savedConvId = localStorage.getItem("estateos_superagent_conv_id");
      if (savedConvId) {
        selectConversation(savedConvId);
      }
      refreshConversations();
    } catch {} finally {
      isInitialized.current = true;
    }
  }, []);

// SessionStorage replaced by Postgres turn persistence

  // Debounced background pre-warming of open page facts (Task 4)
  useEffect(() => {
    const timer = setTimeout(() => {
      prewarmAgentPage({
        pageName: currentPageName,
      });
    }, 350);
    return () => clearTimeout(timer);
  }, [currentPageName]);

  const setIsOpen = (open: boolean) => {
    setIsOpenState(open);
    try {
      localStorage.setItem(STORAGE_KEY, open ? "true" : "false");
    } catch {}
  };

  const toggleOpen = () => {
    setIsOpen(!isOpen);
  };

  const setPanelMode = (mode: "center" | "docked") => {
    setPanelModeState(mode);
    try {
      localStorage.setItem(MODE_KEY, mode);
    } catch {}
  };

  const togglePanelMode = () => {
    const nextMode = panelMode === "center" ? "docked" : "center";
    setPanelMode(nextMode);
  };

  const clearMessages = () => {
    setMessages([DEFAULT_INITIAL_MESSAGE]);
    try {
      sessionStorage.removeItem(MESSAGES_KEY);
    } catch {}
  };

  return (
    <SuperAgentContext.Provider
      value={{
        isOpen,
        setIsOpen,
        toggleOpen,
        panelMode,
        setPanelMode,
        togglePanelMode,
        currentPageName,
        setCurrentPageName,
        selectedContext,
        setSelectedContext,
        messages,
        setMessages,
        clearMessages,
        activeDrawerInfo,
        setActiveDrawerInfo,
        currentConversationId,
        setCurrentConversationId,
        conversationTitle,
        setConversationTitle,
        conversations,
        refreshConversations,
        isHistoryOpen,
        setIsHistoryOpen,
        toggleHistoryOpen,
        startNewChat,
        selectConversation,
        isLoadingConversation,
      }}
    >
      {children}
    </SuperAgentContext.Provider>
  );
}

export function useSuperAgent() {
  const context = useContext(SuperAgentContext);
  if (!context) {
    // Graceful fallback if used outside provider
    return {
      isOpen: false,
      setIsOpen: () => {},
      toggleOpen: () => {},
      panelMode: "center" as const,
      setPanelMode: () => {},
      togglePanelMode: () => {},
      currentPageName: "Today",
      setCurrentPageName: () => {},
      selectedContext: "The whole page",
      setSelectedContext: () => {},
      messages: [],
      setMessages: () => {},
      clearMessages: () => {},
      activeDrawerInfo: null,
      setActiveDrawerInfo: () => {},
      currentConversationId: null,
      setCurrentConversationId: () => {},
      conversationTitle: "New Chat",
      setConversationTitle: () => {},
      conversations: [],
      refreshConversations: async () => {},
      isHistoryOpen: false,
      setIsHistoryOpen: () => {},
      toggleHistoryOpen: () => {},
      startNewChat: () => {},
      selectConversation: async () => {},
      isLoadingConversation: false,
    };
  }
  return context;
}
