"use client";

import React, { createContext, useContext, useState, useEffect } from "react";

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
  documentCard?: {
    title: string;
    size: string;
    url?: string;
  };
  steps?: string[];
  previewCard?: {
    type: string;
    channel?: string;
    recipient?: string;
    unitLabel?: string;
    subject?: string | null;
    body?: string;
    actionId?: string | null;
    caseId?: string | null;
    title?: string;
    subtitle?: string;
    badgeLabel?: string;
    badgeColor?: "orange" | "emerald" | "amber" | "blue" | "red";
    amount?: string;
    status?: string;
    dueDate?: string;
    contractor?: string;
    targetUrl?: string;
  } | null;
  actions?: AssistantAction[];
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
      const storedMsgs = sessionStorage.getItem(MESSAGES_KEY);
      if (storedMsgs) {
        const parsed = JSON.parse(storedMsgs);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setMessages(parsed);
        }
      }
    } catch {}
  }, []);

  // Save messages in sessionStorage whenever they update
  useEffect(() => {
    try {
      if (messages.length > 0) {
        sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
      }
    } catch {}
  }, [messages]);

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
    };
  }
  return context;
}
