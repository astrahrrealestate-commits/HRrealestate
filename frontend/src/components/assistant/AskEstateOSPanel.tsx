"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Calendar,
  Sparkles,
  X,
  Send,
  ArrowUpRight,
  ArrowLeft,
  CheckCircle2,
  Wrench,
  AlertTriangle,
  Clock,
  ArrowRight,
  CornerDownRight,
  Check,
  MessageSquare,
  Mail,
  SendHorizontal,
  ExternalLink,
  Loader2,
  Maximize2,
  Minimize2,
  PanelRight,
  Layout,
  FileText,
  History,
  Plus,
  Pin,
  Trash2,
  Sun,
  Moon,
  UserRound,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { askAgent, approveInboxDraft, approveStandingRule, AssistantCard, CardAction, PreviewCardData, updateAgentConversation } from "@/lib/api";

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

import { useSuperAgent } from "@/context/SuperAgentContext";

interface AskEstateOSPanelProps {
  isOpen?: boolean;
  onClose?: () => void;
  currentPageName?: string;
  selectedContext?: string;
  onActionTriggered?: (actionType: string, payload?: any) => void;
}

export function AskEstateOSPanel({
  isOpen: propIsOpen,
  onClose: propOnClose,
  currentPageName: propPageName,
  selectedContext: propContext,
  onActionTriggered,
}: AskEstateOSPanelProps) {
  const router = useRouter();
  const superAgent = useSuperAgent();
  const isOpen = propIsOpen !== undefined ? propIsOpen : superAgent.isOpen;
  const onClose = propOnClose || (() => superAgent.setIsOpen(false));
  const currentPageName = propPageName || superAgent.currentPageName || "Today";
  const selectedContext = propContext || superAgent.selectedContext || "The whole page";
  const panelMode = superAgent.panelMode || "center";
  const togglePanelMode = superAgent.togglePanelMode;
  const activeDrawerInfo = superAgent.activeDrawerInfo;


  const [inputQuery, setInputQuery] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    try {
      const saved = localStorage.getItem("superagent_theme") as "light" | "dark" | null;
      if (saved === "dark" || saved === "light") {
        setTheme(saved);
      } else {
        setTheme("light");
      }
    } catch {
      setTheme("light");
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    try {
      localStorage.setItem("superagent_theme", next);
    } catch {}
  };

  const isDark = theme === "dark";

  const [sendingCardId, setSendingCardId] = useState<string | null>(null);
  const [approvingCalendarId, setApprovingCalendarId] = useState<string | null>(null);
  const [approvedCalendarIds, setApprovedCalendarIds] = useState<Set<string>>(new Set());
  const [approvingMemoryId, setApprovingMemoryId] = useState<string | null>(null);
  const [approvedMemoryIds, setApprovedMemoryIds] = useState<Set<string>>(new Set());
  const [sentCardIds, setSentCardIds] = useState<Set<string>>(new Set());
  const [sendErrorCardIds, setSendErrorCardIds] = useState<Set<string>>(new Set());
  const [executingActionKey, setExecutingActionKey] = useState<string | null>(null);
  const [completedActionKeys, setCompletedActionKeys] = useState<Set<string>>(new Set());
  const [selectedDraftVariants, setSelectedDraftVariants] = useState<Record<string, number>>({});

  const handleUniversalCardAction = async (action: CardAction, cardId: string) => {
    const actionKey = `${cardId}-${action.label}`;
    if (action.kind === "open_external" && action.targetUrl) {
      window.open(action.targetUrl, "_blank", "noopener,noreferrer");
      return;
    }
    if (action.kind === "navigate" && action.targetUrl) {
      handleNavigate(action.targetUrl);
      return;
    }
    if (action.kind === "api_call" && action.endpoint) {
      setExecutingActionKey(actionKey);
      try {
        const fullUrl = action.endpoint.startsWith("http")
          ? action.endpoint
          : `${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}${action.endpoint}`;
        const res = await fetch(fullUrl, {
          method: action.method || "POST",
          headers: { "Content-Type": "application/json" },
          body: action.payload ? JSON.stringify(action.payload) : undefined,
        });
        if (res.ok) {
          setCompletedActionKeys((prev) => new Set([...prev, actionKey]));
          if (action.endpoint.includes("/approvals/") || action.label.toLowerCase().includes("send")) {
            setSentCardIds((prev) => new Set([...prev, cardId]));
          }
        }
      } catch (e) {
        console.error("Action execution failed", e);
      } finally {
        setExecutingActionKey(null);
      }
    }
  };

  // Use persistent shared messages from SuperAgentContext
  const messages = superAgent.messages;
  const setMessages = superAgent.setMessages;

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut listener: Ctrl+J to toggle, Esc to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        if (isOpen) {
          onClose();
        }
      } else if (e.key === "Escape" && isOpen) {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Focus input on open
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 150);
    }
  }, [isOpen]);

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  // Dynamic workflow suggestions from latest assistant turn, or context-aware section starters
  const lastAssistantMsg = React.useMemo(() => {
    return [...messages].reverse().find((m) => m.sender === "assistant" && m.suggestedPrompts && m.suggestedPrompts.length > 0);
  }, [messages]);

  const suggestedChips = React.useMemo(() => {
    if (lastAssistantMsg?.suggestedPrompts && lastAssistantMsg.suggestedPrompts.length > 0) {
      return lastAssistantMsg.suggestedPrompts.slice(0, 3);
    }
    if (currentPageName.toLowerCase().includes("inbox")) {
      return [
        "Summarize unread emails",
        "Explain leak ticket",
        "Draft work order",
      ];
    }
    if (currentPageName.toLowerCase().includes("money")) {
      return [
        "Why invoice open",
        "Match open payments",
        "Who behind rent",
      ];
    }
    if (currentPageName.toLowerCase().includes("maintenance")) {
      return [
        "Tickets gone quiet",
        "Electrician status",
        "Quotes over limit",
      ];
    }
    return [
      "What do first",
      "Who behind rent",
      "Show active leases",
    ];
  }, [lastAssistantMsg, currentPageName]);

  const handleSendQuery = async (queryText: string) => {
    const trimmed = queryText.trim();
    if (!trimmed) return;

    const userMsg: AssistantMessage = {
      id: `user-${Date.now()}`,
      sender: "user",
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      text: trimmed,
    };

    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputQuery("");
    setIsTyping(true);

    // Extract recent conversation history strings for Super Agent context
    const recentHistory = updatedMessages
      .slice(-6)
      .map((m) => `${m.sender === "user" ? "Owner" : "Agent"}: ${m.text}`);

    try {
      const res = await askAgent(
        trimmed,
        `${currentPageName}: ${selectedContext}`,
        recentHistory,
        superAgent.currentConversationId
      );

      if (res.conversation_id) {
        superAgent.setCurrentConversationId(res.conversation_id);
      }
      if (res.conversation_title) {
        superAgent.setConversationTitle(res.conversation_title);
      }
      superAgent.refreshConversations();

      const parsedActions: AssistantAction[] = [];
      if (res.actions && res.actions.length > 0) {
        parsedActions.push(...res.actions);
      } else if (res.suggestedAction) {
        const fallbackTarget =
          res.previewCard?.targetUrl ||
          (res.previewCard?.caseId ? `/maintenance?ticket=${res.previewCard.caseId}` : "/maintenance");
        parsedActions.push({
          label: res.suggestedAction,
          actionType: "navigate",
          payload: fallbackTarget,
          isPrimary: true,
        });
      }

      const botMsg: AssistantMessage = {
        id: `agent-${Date.now()}`,
        sender: "assistant",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        text: res.answer,
        steps: res.steps,
        previewCard: res.previewCard,
        previewCards: res.previewCards || (res.previewCard ? [res.previewCard] : []),
        cards: res.cards,
        debugInfo: res.debugInfo,
        actions: parsedActions.length > 0 ? parsedActions : undefined,
        suggestedPrompts: res.suggestedPrompts,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch (err) {
      console.error("Super Agent query failed:", err);
      const errorMsg: AssistantMessage = {
        id: `err-${Date.now()}`,
        sender: "assistant",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        text: "I was unable to complete your request right now. Please verify the backend connection and try again.",
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleApproveCalendar = async (cardId: string, eventId?: string | null, payloadUrl?: string | null) => {
    setApprovingCalendarId(cardId);
    try {
      const url = payloadUrl || `/api/calendar/events/${eventId}/approve`;
      const fullUrl = url.startsWith("http") ? url : `${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}${url}`;
      const res = await fetch(fullUrl, { method: "POST", headers: { "Content-Type": "application/json" } });
      if (!res.ok) {
        throw new Error(`Calendar approval failed: ${res.statusText}`);
      }
      setApprovedCalendarIds((prev) => new Set([...prev, cardId]));
    } catch (err) {
      console.error("Failed to approve calendar event:", err);
    } finally {
      setApprovingCalendarId(null);
    }
  };

  const handleApproveMemory = async (cardId: string, memoryId?: string | null, payloadUrl?: string | null) => {
    setApprovingMemoryId(cardId);
    try {
      if (memoryId) {
        await approveStandingRule(memoryId);
      } else if (payloadUrl) {
        const fullUrl = payloadUrl.startsWith("http") ? payloadUrl : `${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}${payloadUrl}`;
        await fetch(fullUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-EstateOS-Client": "dashboard" },
          credentials: "include",
        });
      }
      setApprovedMemoryIds((prev) => new Set([...prev, cardId]));
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("estateos:memory_updated"));
      }
    } catch (err) {
      console.error("Failed to approve memory rule:", err);
    } finally {
      setApprovingMemoryId(null);
    }
  };

  const handleApproveDraft = async (
    cardId: string,
    actionId?: string | null,
    caseId?: string | null,
    customChoice: "d1" | "d2" | "d3" | "ok" = "d1",
    editedText?: string
  ) => {
    setSendingCardId(cardId);
    setSendErrorCardIds((prev) => {
      const next = new Set(prev);
      next.delete(cardId);
      return next;
    });
    try {
      const targetId = actionId || caseId;
      if (!targetId) {
        throw new Error("No approval action or ticket ID available for this draft.");
      }
      const cleanId = targetId.startsWith("case-") ? targetId.replace("case-", "") : targetId;
      const res = await approveInboxDraft(cleanId, customChoice, editedText);
      if (res && res.status === "rejected") {
        throw new Error(res.message || "Approval was rejected by server.");
      }
      setSentCardIds((prev) => new Set([...prev, cardId]));
    } catch (err) {
      console.error("Failed to approve draft directly:", err);
      setSendErrorCardIds((prev) => new Set([...prev, cardId]));
    } finally {
      setSendingCardId(null);
    }
  };

  const handleNavigate = (url: string) => {
    // Only yield/close if in center modal mode OR if navigating to an item that opens a right drawer
    const opensDrawer = url.includes("ticket=") || url.includes("invoice=") || url.includes("tx=") || url.includes("thread=");
    if (panelMode === "center" || opensDrawer) {
      onClose();
    }
    // Perform client-side Next.js navigation without hard-reloading the browser or wiping state
    router.push(url);
    // Dispatch instant sync event for same-page transitions
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("estateos:navigate", { detail: { url } }));
    }
  };

  const handleActionClick = (action: AssistantAction) => {
    if (action.actionType === "approve_memory" && typeof action.payload === "string") {
      const match = action.payload.match(/memory\/([^/]+)\/approve/);
      const memId = match ? match[1] : undefined;
      handleApproveMemory(action.payload, memId, action.payload);
      return;
    }
    if (action.actionType === "approve_calendar" && typeof action.payload === "string") {
      const match = action.payload.match(/events\/([^/]+)\/approve/);
      const eventId = match ? match[1] : undefined;
      handleApproveCalendar(action.payload, eventId, action.payload);
      return;
    }
    if (action.actionType === "external_link" && typeof action.payload === "string") {
      window.open(action.payload, "_blank", "noopener,noreferrer");
      return;
    }
    if (action.actionType === "query" && typeof action.payload === "string") {
      handleSendQuery(action.payload);
      return;
    }
    if (action.actionType === "navigate" && typeof action.payload === "string") {
      handleNavigate(action.payload);
      return;
    }
    if (onActionTriggered) {
      onActionTriggered(action.actionType, action.payload);
    }
  };





  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop: Shown in Center mode (40%) and Fullscreen mode */}
      {(panelMode === "center" || isFullScreen) && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px] transition-opacity duration-200 animate-in fade-in"
        />
      )}

      {/* Main Assistant Panel:
          1. Center Mode (40% default): floating centered modal spotlight
          2. Docked Mode (30%): right sidecar docked flush against the screen
          3. Fullscreen Mode: expanded modal
      */}
      <aside
        className={cn(
          "shadow-2xl flex flex-col justify-between font-sans transition-colors duration-150",
          isDark
            ? "bg-[#0E1113] text-[#F3F4F6] border-[#22282E]"
            : "bg-[#FFFFFF] text-[#0A0A0A] border-[#E8E8E5]",

          isFullScreen
            ? "fixed inset-2 md:inset-6 z-50 rounded-[18px] border overflow-hidden transition-all duration-200 animate-in zoom-in-95"
            : panelMode === "center"
            ? "fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[95vw] sm:w-[85vw] md:w-[40vw] md:min-w-[500px] md:max-w-[720px] h-[82vh] max-h-[850px] rounded-[18px] border overflow-hidden transition-all duration-200 animate-in zoom-in-95"
            : "fixed inset-0 z-50 md:sticky md:top-0 md:right-0 md:z-30 w-full md:w-[32vw] md:min-w-[360px] md:max-w-[520px] h-dvh md:h-screen md:border-l flex-shrink-0 overflow-hidden transition-all duration-200 animate-in slide-in-from-right-4"
        )}
      >
        {/* 1. Header Bar with Integrated Context Tag (No extra box bar needed) */}
        <div
          className={cn(
            "h-14 px-4 sm:px-5 border-b flex items-center justify-between flex-shrink-0 transition-colors",
            isDark ? "bg-[#0E1113] border-[#1A1F24]" : "bg-[#FFFFFF] border-[#E8E8E5]"
          )}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            {/* Mobile Back Button */}
            <button
              onClick={onClose}
              className={cn(
                "md:hidden p-1.5 -ml-1 rounded-[8px] transition-colors cursor-pointer",
                isDark
                  ? "text-[#9CA3AF] hover:text-white hover:bg-[#1A1F24]"
                  : "text-[#6B7280] hover:text-[#0A0A0A] hover:bg-[#F0F0EE]"
              )}
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 stroke-[2]" />
            </button>

            {/* AI Agent Icon */}
            <div
              className={cn(
                "w-7 h-7 rounded-[8px] border flex items-center justify-center shadow-xs shrink-0",
                isDark
                  ? "bg-[#182026] border-[#2A3540] text-emerald-300"
                  : "bg-[#FFF1E7] border-[#F25C05]/30 text-[#F25C05]"
              )}
            >
              <Sparkles className="w-3.5 h-3.5" />
            </div>

            {/* Title & Page Context */}
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={cn(
                  "font-heading font-semibold text-[14px] tracking-tight shrink-0",
                  isDark ? "text-[#F9FAFB]" : "text-[#0A0A0A]"
                )}
              >
                Super Agent
              </span>
              <span
                className={cn(
                  "text-[10px] font-mono uppercase px-1.5 py-0.5 rounded-[5px] shrink-0 border",
                  isDark
                    ? "bg-[#161A1D] text-[#94A3B8] border-[#252B32]"
                    : "bg-[#F6F6F4] text-[#6B7280] border-[#E8E8E5]"
                )}
              >
                Concierge
              </span>

              {/* History Button */}
              <button
                type="button"
                onClick={superAgent.toggleHistoryOpen}
                className={cn(
                  "w-7 h-7 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer shrink-0 ml-1",
                  superAgent.isHistoryOpen
                    ? isDark
                      ? "bg-[#1E2328] border-[#F25C05]/50 text-white"
                      : "bg-[#FFF1E7] border-[#F25C05] text-[#F25C05]"
                    : isDark
                      ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                      : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
                )}
                title="Toggle Conversation History"
              >
                <History className="w-3.5 h-3.5" />
              </button>

              {/* New Chat Button */}
              <button
                type="button"
                onClick={superAgent.startNewChat}
                className={cn(
                  "hidden sm:flex items-center gap-1 px-2 py-1 rounded-[6px] border text-[11px] font-medium transition-colors cursor-pointer shrink-0",
                  isDark
                    ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#CBD5E1] hover:text-white"
                    : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#222222] hover:text-[#0A0A0A]"
                )}
                title="Start a new conversation thread"
              >
                <Plus className="w-3 h-3 text-[#F25C05]" />
                <span>New Chat</span>
              </button>

              {/* Active Conversation Title */}
              {superAgent.conversationTitle && superAgent.conversationTitle !== "New Chat" && (
                <span
                  className={cn(
                    "hidden md:inline-block text-[11.5px] font-medium px-2 py-0.5 rounded-[5px] truncate max-w-[140px] border",
                    isDark
                      ? "text-emerald-300 bg-emerald-500/10 border-emerald-500/25"
                      : "text-emerald-700 bg-emerald-50 border-emerald-200 font-semibold"
                  )}
                >
                  {superAgent.conversationTitle}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {/* Quick Toggle to Active Item Drawer (Unified Right Rail) */}
            {activeDrawerInfo && (
              <button
                type="button"
                onClick={onClose}
                className={cn(
                  "hidden sm:inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold border rounded-[7px] transition-colors cursor-pointer shrink-0",
                  isDark
                    ? "text-[#F25C05] bg-[#161A1D] hover:bg-[#20262B] border-[#252B32]"
                    : "text-[#B93C00] bg-[#FFF1E7] hover:bg-[#FFE5D4] border-[#F25C05]/30"
                )}
                title={`Switch back to ${activeDrawerInfo.kind} ${activeDrawerInfo.title}`}
              >
                <ArrowLeft className="w-3 h-3 text-[#F25C05]" />
                <span>Back to {activeDrawerInfo.kind} {activeDrawerInfo.title}</span>
              </button>
            )}

            {/* Mode Switcher: Center (40%) <-> Dock (30%) */}
            <button
              onClick={togglePanelMode}
              className={cn(
                "hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-[7px] border text-[11px] transition-colors cursor-pointer",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
              )}
              title={panelMode === "center" ? "Dock to right side (30%)" : "Float in center (40%)"}
            >
              {panelMode === "center" ? (
                <>
                  <PanelRight className="w-3.5 h-3.5" />
                  <span>Dock 30%</span>
                </>
              ) : (
                <>
                  <Layout className="w-3.5 h-3.5" />
                  <span>Center 40%</span>
                </>
              )}
            </button>

            {/* Fullscreen / Restore Toggle Button */}
            <button
              onClick={() => setIsFullScreen((prev) => !prev)}
              className={cn(
                "hidden md:flex w-8 h-8 rounded-[7px] border items-center justify-center transition-colors cursor-pointer",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
              )}
              title={isFullScreen ? "Restore Window" : "Expand to Full Screen"}
            >
              {isFullScreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
            </button>

            {/* Theme Toggle: Light / Dark Mode */}
            <button
              onClick={toggleTheme}
              className={cn(
                "w-8 h-8 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-amber-300 hover:text-amber-200"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#6B7280] hover:text-[#0A0A0A]"
              )}
              title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {isDark ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
            </button>

            {/* Close Button */}
            <button
              onClick={onClose}
              className={cn(
                "w-8 h-8 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
              )}
              title="Close (Esc)"
            >
              <X className="w-4 h-4 stroke-[2]" />
            </button>
          </div>
        </div>

        {/* Main Body with Collapsible History Drawer */}
        <div className="flex-1 flex min-h-0 overflow-hidden relative">
          {/* History Drawer Sidebar */}
          {superAgent.isHistoryOpen && (
            <div
              className={cn(
                "w-[230px] border-r flex flex-col shrink-0 animate-in slide-in-from-left-4 duration-150 z-20 transition-colors",
                isDark ? "border-[#1E2328] bg-[#0A0C0E]" : "border-[#E8E8E5] bg-[#FBFBFA]"
              )}
            >
              <div
                className={cn(
                  "p-3 border-b flex items-center justify-between",
                  isDark ? "border-[#1E2328]" : "border-[#E8E8E5]"
                )}
              >
                <span
                  className={cn(
                    "text-[11px] font-semibold uppercase font-mono tracking-wider",
                    isDark ? "text-[#CBD5E1]" : "text-[#444444]"
                  )}
                >
                  Chats ({superAgent.conversations.length})
                </span>
                <button
                  type="button"
                  onClick={superAgent.startNewChat}
                  className={cn(
                    "px-2 py-1 rounded-[6px] text-[11px] font-medium flex items-center gap-1 cursor-pointer transition-colors",
                    isDark
                      ? "bg-[#1E2328] hover:bg-[#28323B] text-white"
                      : "bg-[#FFFFFF] hover:bg-[#F0F0EE] border border-[#E8E8E5] text-[#0A0A0A]"
                  )}
                  title="Start a new conversation"
                >
                  <Plus className="w-3 h-3 text-[#F25C05]" />
                  <span>New</span>
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-2 space-y-3">
                {superAgent.conversations.length === 0 ? (
                  <div className={cn("p-3 text-center text-[11.5px]", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                    No saved chats yet.
                  </div>
                ) : (
                  ["Today", "Yesterday", "Earlier"].map((bucket) => {
                    const bucketConvs = superAgent.conversations.filter(
                      (conv_it) => conv_it.time_bucket === bucket
                    );
                    if (bucketConvs.length === 0) return null;

                    return (
                      <div key={bucket} className="space-y-1">
                        <div className={cn("px-2 py-1 text-[10px] font-mono uppercase", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                          {bucket}
                        </div>
                        {bucketConvs.map((conv) => {
                          const isActive = conv.id === superAgent.currentConversationId;
                          return (
                            <div
                              key={conv.id}
                              onClick={() => superAgent.selectConversation(conv.id)}
                              className={cn(
                                "group p-2 rounded-[8px] transition-all cursor-pointer flex items-center justify-between gap-1.5 text-left",
                                isActive
                                  ? isDark
                                    ? "bg-[#161B20] text-white border-l-2 border-[#F25C05]"
                                    : "bg-[#FFFFFF] text-[#0A0A0A] border-l-2 border-[#F25C05] shadow-xs border-y border-r border-[#E8E8E5]"
                                  : isDark
                                    ? "hover:bg-[#13161A] text-[#94A3B8] hover:text-[#E2E8F0]"
                                    : "hover:bg-[#F0F0EE] text-[#444444] hover:text-[#0A0A0A]"
                              )}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="text-[12px] font-medium truncate">
                                  {conv.title}
                                </div>
                                <div className={cn("text-[10.5px] truncate", isDark ? "text-[#64748B]" : "text-[#6B7280]")}>
                                  {conv.snippet}
                                </div>
                              </div>
                              <div className="opacity-0 group-hover:opacity-100 flex items-center gap-1 shrink-0">
                                <button
                                  type="button"
                                  title={conv.pinned ? "Unpin" : "Pin"}
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    await updateAgentConversation(conv.id, { pinned: !conv.pinned });
                                    superAgent.refreshConversations();
                                  }}
                                  className={cn("p-1 transition-colors", isDark ? "hover:text-white" : "hover:text-[#0A0A0A]")}
                                >
                                  <Pin className={cn("w-3 h-3", conv.pinned ? "text-[#F25C05] fill-[#F25C05]" : isDark ? "text-[#64748B]" : "text-[#9CA3AF]")} />
                                </button>
                                <button
                                  type="button"
                                  title="Hide thread"
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    await updateAgentConversation(conv.id, { hidden: true });
                                    if (conv.id === superAgent.currentConversationId) {
                                      superAgent.startNewChat();
                                    }
                                    superAgent.refreshConversations();
                                  }}
                                  className="p-1 hover:text-rose-500 transition-colors"
                                >
                                  <Trash2 className={cn("w-3 h-3", isDark ? "text-[#64748B]" : "text-[#9CA3AF]")} />
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {/* Center Column: Messages & Input */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {/* 2. Scrollable Message Thread */}
            <div
              className={cn(
                "flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-5 space-y-4 text-[13.5px] leading-relaxed min-w-0 w-full transition-colors",
                isDark ? "bg-[#0E1113]" : "bg-[#F6F6F4]"
              )}
            >
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex flex-col gap-1 max-w-[96%] min-w-0",
                msg.sender === "user" ? "ml-auto items-end" : "mr-auto items-start w-full"
              )}
            >
              {/* Message Bubble: Clean border, no bulky shadow */}
              <div
                className={cn(
                  "p-3.5 sm:p-4 rounded-[14px] text-[13.5px] min-w-0 max-w-full break-words [overflow-wrap:anywhere]",
                  msg.sender === "user"
                    ? isDark
                      ? "bg-[#1F2730] border border-[#2D3945] text-[#F9FAFB] rounded-tr-none"
                      : "bg-[#0A0A0A] border border-[#0A0A0A] text-[#FFFFFF] rounded-tr-none"
                    : isDark
                      ? "bg-[#14171A] border border-[#222830] text-[#E5E7EB] rounded-tl-none shadow-sm w-full"
                      : "bg-[#FFFFFF] border border-[#E8E8E5] text-[#0A0A0A] rounded-tl-none shadow-xs w-full"
                )}
              >
                <div
                  className="whitespace-pre-line leading-relaxed break-words [overflow-wrap:anywhere] min-w-0 max-w-full"
                  dangerouslySetInnerHTML={{
                    __html: formatMarkdown(msg.text, isDark),
                  }}
                />

                {/* Read citation: subtle inline text */}
                {msg.readSource && (
                  <div
                    className={cn(
                      "mt-2.5 pt-2 border-t text-[11px] flex items-center gap-1.5 font-mono",
                      isDark ? "border-[#1E2328] text-[#64748B]" : "border-[#E8E8E5] text-[#6B7280]"
                    )}
                  >
                    <span className={isDark ? "text-[#94A3B8]" : "text-[#4B5563]"}>Read:</span>
                    <span className="truncate">{msg.readSource}</span>
                  </div>
                )}

                {/* Facts: Minimal 2-column key/value list without heavy nested boxes */}
                {msg.facts && msg.facts.length > 0 && (
                  <div
                    className={cn(
                      "mt-3 pt-2.5 border-t grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px]",
                      isDark ? "border-[#1E2328]" : "border-[#E8E8E5]"
                    )}
                  >
                    {msg.facts.map((fact, idx) => (
                      <div key={idx} className="flex flex-col">
                        <span
                          className={cn(
                            "text-[10px] uppercase font-mono tracking-wider mb-0.5",
                            isDark ? "text-[#64748B]" : "text-[#6B7280]"
                          )}
                        >
                          {fact.label}
                        </span>
                        <span
                          className={cn(
                            "font-medium truncate",
                            fact.isAlert ? "text-[#F25C05]" : isDark ? "text-[#E2E8F0]" : "text-[#0A0A0A]"
                          )}
                        >
                          {fact.value}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Live Step Checklist: Filter out internal technical/database jargon */}
                {(() => {
                  const validSteps = filterValidSteps(msg.steps);
                  if (validSteps.length === 0) return null;
                  return (
                    <div
                      className={cn(
                        "mt-2.5 space-y-1.5 text-[12px]",
                        isDark ? "text-[#94A3B8]" : "text-[#4B5563]"
                      )}
                    >
                      {validSteps.map((st, sIdx) => (
                        <div key={sIdx} className="flex items-center gap-2">
                          <Check className={cn("w-3.5 h-3.5 shrink-0", isDark ? "text-emerald-300" : "text-emerald-600")} />
                          <span className="leading-tight">{st}</span>
                        </div>
                      ))}
                    </div>
                  );
                })()}

                {/* Mini Preview Workspace Cards (Smart limit up to 3 cards) */}
                {(() => {
                  const cardsToRender: PreviewCardData[] = (msg.previewCards && msg.previewCards.length > 0)
                    ? msg.previewCards
                    : (msg.previewCard ? [msg.previewCard] : []);
                  if (cardsToRender.length === 0) return null;

                  return (
                    <div className="space-y-2.5 mt-3">
                      {cardsToRender.map((pCard: PreviewCardData, cardIdx: number) => (
                        <div
                          key={pCard.actionId || pCard.caseId || `preview-${cardIdx}`}
                          className={cn(
                            "rounded-[10px] border p-3.5 space-y-2.5 shadow-xs animate-in fade-in-50 duration-150 min-w-0 max-w-full overflow-hidden transition-colors",
                            isDark ? "bg-[#15181C] border-[#222830]" : "bg-[#FBFBFA] border-[#E8E8E5]"
                          )}
                        >
                    {pCard.type === "draft_message" && pCard.personaName && (
                      <div
                        className={cn("flex items-center gap-1.5 text-[10.5px] font-medium", isDark ? "text-[#94A3B8]" : "text-[#6B7280]")}
                        title={`Drafted using the persona file "${pCard.personaName}" (version ${pCard.personaVersion ?? 1})`}
                      >
                        <UserRound className="w-3 h-3 shrink-0" />
                        <span>Acting as Harjot</span>
                        <span className="font-normal opacity-80 truncate">· {pCard.personaName} v{pCard.personaVersion ?? 1}</span>
                      </div>
                    )}
                    {/* 1. Case Snapshot Card */}
                    {pCard.type === "case_summary" ? (
                      (() => {
                        const cleanBody = cleanCardBody(pCard.body || pCard.title);
                        const contractor = resolveContractorName(pCard);
                        const isUrgent = pCard.badgeLabel === "URGENT" || pCard.badgeColor === "rose" || /emergency|urgent/i.test(pCard.title || "");
                        const poCap = pCard.amount || (cleanBody.match(/€\s*\d+(?:[.,]\d+)?/)?.[0] ? `${cleanBody.match(/€\s*\d+(?:[.,]\d+)?/)?.[0]} PO Cap` : null);

                        return (
                          <div className="space-y-2.5">
                            <div className="flex items-center justify-between text-[11px] gap-2">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className={cn(
                                  "font-mono text-[10px] font-semibold uppercase px-2 py-0.5 rounded border shrink-0",
                                  isUrgent
                                    ? isDark
                                      ? "bg-rose-950/60 text-rose-300 border-rose-800/50"
                                      : "bg-rose-50 text-rose-700 border-rose-200"
                                    : isDark
                                      ? "bg-blue-950/60 text-blue-300 border-blue-800/50"
                                      : "bg-blue-50 text-blue-700 border-blue-200"
                                )}>
                                  {isUrgent ? "URGENT" : "TICKET"}
                                </span>
                                <span className={cn("font-medium truncate", isDark ? "text-[#F3F4F6]" : "text-[#0A0A0A]")}>
                                  {pCard.unitLabel || "Portfolio"}
                                </span>
                              </div>
                              {pCard.status && (
                                <span className={cn(
                                  "text-[10.5px] font-mono capitalize px-2 py-0.5 rounded border shrink-0",
                                  isDark ? "bg-[#1A1F26] border-[#262F3A] text-[#94A3B8]" : "bg-[#FFFFFF] border-[#E8E8E5] text-[#4B5563]"
                                )}>
                                  {pCard.status}
                                </span>
                              )}
                            </div>
                            <div className={cn("text-[12.5px] leading-relaxed font-sans break-words [overflow-wrap:anywhere]", isDark ? "text-[#E2E8F0]" : "text-[#1F2937]")}>
                              {cleanBody}
                            </div>
                            {(contractor || poCap) && (
                              <div className={cn("flex flex-wrap items-center justify-between gap-2 pt-2 border-t text-[11px]", isDark ? "border-[#1E2328]" : "border-[#E8E8E5]")}>
                                {contractor ? (
                                  <div className={cn("flex items-center gap-1.5", isDark ? "text-[#94A3B8]" : "text-[#6B7280]")}>
                                    <Wrench className={cn("w-3.5 h-3.5 shrink-0", isDark ? "text-[#64748B]" : "text-[#9CA3AF]")} />
                                    <span>Contractor: <strong className={cn("font-medium", isDark ? "text-[#E2E8F0]" : "text-[#0A0A0A]")}>{contractor}</strong></span>
                                  </div>
                                ) : <span />}
                                {poCap && (
                                  <span className={cn(
                                    "font-mono text-[10.5px] font-semibold px-2 py-0.5 rounded border",
                                    isDark ? "text-amber-300 bg-amber-950/40 border-amber-800/40" : "text-amber-800 bg-amber-50 border-amber-200"
                                  )}>
                                    {poCap}
                                  </span>
                                )}
                              </div>
                            )}
                            <div className={cn("pt-1 flex items-center justify-end border-t", isDark ? "border-[#1E2328]/60" : "border-[#E8E8E5]")}>
                              <button
                                type="button"
                                onClick={() => {
                                  if (pCard?.targetUrl?.startsWith("http")) {
                                    window.open(pCard.targetUrl, "_blank", "noopener,noreferrer");
                                  } else {
                                    handleNavigate(pCard?.targetUrl || (pCard?.caseId ? `/maintenance?ticket=${pCard.caseId}` : "/maintenance"));
                                  }
                                }}
                                className="text-[11px] font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                              >
                                <span>Open in Maintenance</span>
                                <ExternalLink className="w-3 h-3" />
                              </button>
                            </div>
                          </div>
                        );
                      })()
                    ) : pCard.type === "financial_item" ? (
                      /* 2. Financial Arrears / Ledger Card (Amount is the important highlight) */
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className={cn(
                            "font-mono text-[10px] uppercase px-1.5 py-0.5 rounded border",
                            isDark ? "bg-[#1F252C] text-[#CBD5E1] border-[#29323B]" : "bg-[#FFFFFF] text-[#4B5563] border-[#E8E8E5]"
                          )}>
                            {pCard.badgeLabel || "ARREARS"}
                          </span>
                          <span className={cn("font-mono text-[14px] font-bold", isDark ? "text-rose-400" : "text-rose-600")}>
                            {pCard.amount}
                          </span>
                        </div>
                        <div className={cn("text-[13px] font-semibold break-words", isDark ? "text-[#F9FAFB]" : "text-[#0A0A0A]")}>
                          {pCard.title}
                        </div>
                        <div className={cn("text-[12px] leading-relaxed break-words [overflow-wrap:anywhere]", isDark ? "text-[#94A3B8]" : "text-[#4B5563]")}>
                          {cleanCardBody(pCard.subtitle || pCard.body)}
                        </div>
                        <div className={cn("pt-2 flex items-center justify-between border-t text-[11px]", isDark ? "border-[#1E2328]" : "border-[#E8E8E5]")}>
                          <span className={cn("font-mono text-[10.5px]", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                            {pCard.dueDate ? `Due: ${pCard.dueDate}` : pCard.unitLabel}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleNavigate(pCard?.targetUrl || "/money")}
                            className="font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                          >
                            <span>Open in Money</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    ) : pCard.type === "calendar_item" ? (
                      /* Calendar Appointment Proposal Card */
                      <div className="space-y-2.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B] flex items-center gap-1">
                              <Calendar className="w-3 h-3 text-[#F25C05]" />
                              {pCard.badgeLabel || "GOOGLE CALENDAR"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {pCard.unitLabel || "Portfolio Visit"}
                            </span>
                          </div>
                          <span
                            className={cn(
                              "text-[10.5px] font-mono capitalize",
                              approvedCalendarIds.has(msg.id) || pCard.status === "confirmed"
                                ? "text-emerald-400 font-semibold"
                                : "text-amber-400"
                            )}
                          >
                            {approvedCalendarIds.has(msg.id) || pCard.status === "confirmed" ? "Confirmed" : "Proposed"}
                          </span>
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB]">
                          {pCard.title}
                        </div>
                        <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] space-y-1.5 text-[12px] text-[#CBD5E1]">
                          <div className="flex items-center gap-1.5 text-[#E2E8F0]">
                            <Clock className="w-3.5 h-3.5 text-[#F25C05]" />
                            <span className="font-medium">{pCard.dueDate || pCard.subtitle}</span>
                          </div>
                          {pCard.contractor && (
                            <div className="text-[#94A3B8] text-[11.5px]">
                              Contractor: <span className="text-[#F1F5F9]">{pCard.contractor}</span>
                            </div>
                          )}
                          {pCard.body && (
                            <div className="text-[11.5px] text-[#94A3B8] whitespace-pre-line border-t border-[#1E2328] pt-1 mt-1">
                              {pCard.body}
                            </div>
                          )}
                        </div>
                        <div className="pt-1.5 flex items-center justify-between border-t border-[#1E2328]">
                          <span className="text-[10.5px] font-mono text-[#64748B]">
                            {approvedCalendarIds.has(msg.id) || pCard.status === "confirmed"
                              ? "Synced to Google Calendar"
                              : "Requires 1-click confirmation"}
                          </span>
                          {approvedCalendarIds.has(msg.id) || pCard.status === "confirmed" ? (
                            <div className="flex items-center gap-1.5 text-emerald-400 text-[11.5px] font-semibold">
                              <CheckCircle2 className="w-4 h-4" />
                              <span>Added to Google Calendar</span>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleApproveCalendar(msg.id, pCard?.actionId)}
                              disabled={approvingCalendarId === msg.id}
                              className="px-3 py-1.5 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                            >
                              {approvingCalendarId === msg.id ? (
                                <>
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  <span>Syncing...</span>
                                </>
                              ) : (
                                <>
                                  <Check className="w-3.5 h-3.5" />
                                  <span>Approve & Add to Calendar</span>
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    ) : pCard.type === "document_item" ? (
                      /* 3. Document / Google Drive Verified Match Card */
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B] flex items-center gap-1">
                              <FileText className="w-3 h-3 text-[#F25C05]" />
                              {pCard.badgeLabel || "GOOGLE DRIVE"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {pCard.unitLabel || "Portfolio Document"}
                            </span>
                          </div>
                          {pCard.status && (
                            <span className="text-[10.5px] font-mono text-emerald-400">
                              {pCard.status}
                            </span>
                          )}
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB]">
                          {pCard.title}
                        </div>
                        {pCard.body && (
                          <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] text-[12px] text-[#CBD5E1] font-sans leading-relaxed break-words [overflow-wrap:anywhere]">
                            {pCard.body}
                          </div>
                        )}
                        <div className="pt-1.5 flex items-center justify-end">
                          <button
                            type="button"
                            onClick={() => {
                              if (pCard?.targetUrl?.startsWith("http")) {
                                window.open(pCard.targetUrl, "_blank", "noopener,noreferrer");
                              } else {
                                handleNavigate(pCard?.targetUrl || "/documents");
                              }
                            }}
                            className="text-[11px] font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                          >
                            <span>Open in Google Drive</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    ) : pCard.type === "memory_item" ? (
                      /* 4. Standing Rule / Policy Proposal Card */
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B] flex items-center gap-1">
                              <Sparkles className="w-3 h-3 text-[#F25C05]" />
                              {pCard.badgeLabel || "POLICY PROPOSAL"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {pCard.unitLabel || "Company Portfolio"}
                            </span>
                          </div>
                          <span className={cn(
                            "text-[10.5px] font-mono",
                            approvedMemoryIds.has(pCard.actionId || "") ? "text-emerald-400" : "text-amber-400"
                          )}>
                            {approvedMemoryIds.has(pCard.actionId || "") ? "Active Rule" : "Pending Activation"}
                          </span>
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB]">
                          {pCard.title || "Proposed Standing Rule"}
                        </div>
                        {pCard.body && (
                          <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] text-[12px] text-[#CBD5E1] font-sans leading-relaxed break-words [overflow-wrap:anywhere]">
                            • {pCard.body}
                          </div>
                        )}
                        <div className="pt-1.5 flex items-center justify-between border-t border-[#1E2328]">
                          <span className="text-[10.5px] font-mono text-[#64748B]">
                            {approvedMemoryIds.has(pCard.actionId || "") ? "Enforced across all workflows" : "Requires owner sign-off"}
                          </span>
                          {approvedMemoryIds.has(pCard.actionId || "") ? (
                            <div className="flex items-center gap-1.5 text-emerald-400 text-[11.5px] font-semibold">
                              <CheckCircle2 className="w-4 h-4" />
                              <span>Rule Activated</span>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleApproveMemory(pCard?.actionId || msg.id, pCard?.actionId)}
                              disabled={approvingMemoryId === (pCard?.actionId || msg.id)}
                              className="px-3 py-1.5 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                            >
                              {approvingMemoryId === (pCard?.actionId || msg.id) ? (
                                <>
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  <span>Activating...</span>
                                </>
                              ) : (
                                <>
                                  <Check className="w-3.5 h-3.5" />
                                  <span>Activate Standing Rule</span>
                                </>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    ) : pCard.type === "notice" ? (
                      /* 5. Notice / Alert Card (WP2: Failed draft / Groq timeout / Rate limit) */
                      <div className="space-y-2.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className={cn(
                            "font-mono text-[10px] uppercase px-1.5 py-0.5 rounded border",
                            isDark ? "bg-amber-500/15 text-amber-400 border-amber-500/30" : "bg-amber-50 text-amber-800 border-amber-200"
                          )}>
                            {pCard.badgeLabel || "NOTICE"}
                          </span>
                          <span className={cn("text-[10.5px] font-mono", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                            {pCard.unitLabel || "Action Required"}
                          </span>
                        </div>

                        <div className={cn("text-[13px] font-semibold", isDark ? "text-[#F9FAFB]" : "text-[#0A0A0A]")}>
                          {pCard.title || "Action Notice"}
                        </div>

                        <div className={cn(
                          "p-2.5 rounded-[8px] text-[12px] leading-relaxed font-sans break-words [overflow-wrap:anywhere] border",
                          isDark ? "bg-[#0E1113] border-amber-500/20 text-[#E2E8F0]" : "bg-[#FFFBEB] border-amber-200 text-[#78350F]"
                        )}>
                          {pCard.body}
                        </div>

                        <div className={cn("pt-1 flex items-center justify-between gap-2 border-t", isDark ? "border-[#1E2328]" : "border-[#E8E8E5]")}>
                          <span className={cn("text-[10px] font-mono", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                            Status: {pCard.status || "Pending Review"}
                          </span>
                          <div className="flex items-center gap-2">
                            {pCard.caseId && (
                              <button
                                type="button"
                                onClick={() => handleSendQuery(`draft a reply for case ${pCard?.caseId}`)}
                                className={cn(
                                  "px-2.5 py-1 rounded-[6px] border text-[11px] font-medium transition-colors cursor-pointer",
                                  isDark
                                    ? "bg-[#181818] hover:bg-[#222222] border-[#262626] text-[#FFFFFF]"
                                    : "bg-[#0A0A0A] hover:bg-[#222222] border-[#0A0A0A] text-[#FFFFFF]"
                                )}
                              >
                                Retry Draft
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => handleNavigate(pCard?.targetUrl || `/inbox?thread=case-${pCard?.caseId || ""}`)}
                              className="text-[11px] text-[#F25C05] hover:underline flex items-center gap-1 cursor-pointer font-medium"
                            >
                              <span>Open in Inbox</span>
                              <ExternalLink className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* 6. Message Draft Card (WhatsApp / Gmail) */
                      (() => {
                        const rawVariants = (pCard.variants && pCard.variants.length > 0)
                          ? pCard.variants
                          : (pCard.body ? [pCard.body] : []);
                        const variantIndex = selectedDraftVariants[msg.id] ?? 0;
                        const activeDraftBody = rawVariants[variantIndex] || pCard.body || "";
                        const choiceKey = variantIndex === 0 ? "d1" : "d2";
                        const cleanPhone = (pCard.recipient || "").replace(/[^0-9]/g, "");

                        const dynamicExternalUrl = pCard.channel?.toLowerCase() === "whatsapp" && cleanPhone
                          ? `https://wa.me/${cleanPhone}?text=${encodeURIComponent(activeDraftBody)}`
                          : pCard.channel?.toLowerCase() === "gmail" && pCard.recipient
                          ? `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(pCard.recipient)}&su=${encodeURIComponent(pCard.subject || "Maintenance Update")}&body=${encodeURIComponent(activeDraftBody)}`
                          : pCard.externalUrl;

                        return (
                          <div className="space-y-2.5">
                            <div className="flex items-center justify-between text-[11px] gap-2">
                              <span className={cn(
                                "font-mono text-[10px] uppercase px-1.5 py-0.5 rounded border shrink-0",
                                isDark ? "bg-[#1F252C] text-[#CBD5E1] border-[#29323B]" : "bg-[#FFFFFF] text-[#4B5563] border-[#E8E8E5]"
                              )}>
                                Draft · {pCard.channel || "whatsapp"}
                              </span>
                              <span className="font-mono text-[10.5px] truncate text-right">
                                {pCard.recipient ? (
                                  <span className={isDark ? "text-[#64748B]" : "text-[#6B7280]"}>{pCard.recipient}</span>
                                ) : (
                                  <span className={cn("font-sans text-[10px] font-semibold", isDark ? "text-amber-400" : "text-amber-700")}>
                                    {pCard.channel?.toLowerCase() === "gmail" ? "⚠️ No recipient email on file" : "⚠️ No recipient phone on file"}
                                  </span>
                                )}
                              </span>
                            </div>

                            {/* Multi-Draft Option Switcher */}
                            {rawVariants.length > 1 && (
                              <div className={cn(
                                "flex items-center gap-1 p-1 rounded-[7px] border w-fit",
                                isDark ? "bg-[#141920] border-[#222933]" : "bg-[#F3F4F6] border-[#E5E7EB]"
                              )}>
                                {rawVariants.map((_, vIdx) => {
                                  const isSelected = (variantIndex === vIdx);
                                  return (
                                    <button
                                      key={vIdx}
                                      type="button"
                                      onClick={() => setSelectedDraftVariants((prev) => ({ ...prev, [msg.id]: vIdx }))}
                                      className={cn(
                                        "px-2.5 py-1 text-[11px] rounded-[5px] transition-all cursor-pointer flex items-center gap-1.5",
                                        isSelected
                                          ? isDark
                                            ? "bg-[#2A3441] text-[#FFFFFF] font-semibold shadow-xs"
                                            : "bg-[#FFFFFF] text-[#0A0A0A] font-semibold shadow-xs"
                                          : isDark
                                            ? "text-[#94A3B8] hover:text-[#FFFFFF]"
                                            : "text-[#6B7280] hover:text-[#0A0A0A]"
                                      )}
                                    >
                                      <span>{vIdx === 0 ? "Option 1 (Recommended)" : "Option 2 (Alternative)"}</span>
                                    </button>
                                  );
                                })}
                              </div>
                            )}

                            <div className={cn(
                              "p-2.5 rounded-[8px] border text-[12px] italic whitespace-pre-line leading-relaxed font-sans break-words [overflow-wrap:anywhere]",
                              isDark ? "bg-[#0E1113] border-[#1E2328] text-[#E2E8F0]" : "bg-[#FFFFFF] border-[#E8E8E5] text-[#111827]"
                            )}>
                              "{activeDraftBody || "(Draft empty)"}"
                            </div>

                            <div className="pt-1 flex flex-wrap items-center justify-between gap-2">
                              <div className="flex flex-wrap items-center gap-2">
                                {sentCardIds.has(msg.id) ? (
                                  <div className={cn("flex items-center gap-1.5 text-[11.5px] font-medium py-1", isDark ? "text-emerald-400" : "text-emerald-700")}>
                                    <Check className="w-4 h-4 stroke-[2.5]" />
                                    <span>Dispatched to {pCard.channel || "WhatsApp"}</span>
                                  </div>
                                ) : sendErrorCardIds.has(msg.id) ? (
                                  <div className="flex items-center gap-2">
                                    <span className={cn("text-[11px]", isDark ? "text-rose-400" : "text-rose-600")}>Failed to dispatch draft.</span>
                                    <button
                                      type="button"
                                      onClick={() => handleApproveDraft(msg.id, pCard?.actionId, pCard?.caseId, choiceKey, activeDraftBody)}
                                      className="text-[11px] text-[#F25C05] hover:underline cursor-pointer font-semibold"
                                    >
                                      Retry
                                    </button>
                                  </div>
                                ) : pCard.status && pCard.status !== "pending" ? (
                                  <div className={cn("flex items-center gap-1.5 text-[11.5px] font-medium py-1 capitalize", isDark ? "text-[#94A3B8]" : "text-[#6B7280]")}>
                                    <span>Status: {pCard.status}</span>
                                  </div>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={() => handleApproveDraft(msg.id, pCard?.actionId, pCard?.caseId, choiceKey, activeDraftBody)}
                                    disabled={sendingCardId === msg.id || !pCard?.recipient}
                                    className="px-3 py-1.5 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] text-[#FFFFFF] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                                    title={!pCard?.recipient ? "Cannot dispatch: recipient is missing" : "Approve and send"}
                                  >
                                    {sendingCardId === msg.id ? (
                                      <>
                                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                        <span>Sending...</span>
                                      </>
                                    ) : (
                                      <>
                                        <SendHorizontal className="w-3.5 h-3.5" />
                                        <span>Accept and send</span>
                                      </>
                                    )}
                                  </button>
                                )}

                                {dynamicExternalUrl && (
                                  <button
                                    type="button"
                                    onClick={() => window.open(dynamicExternalUrl, "_blank", "noopener,noreferrer")}
                                    className={cn(
                                      "px-2.5 py-1.5 rounded-[7px] font-medium text-[11.5px] flex items-center gap-1.5 transition-all cursor-pointer border",
                                      pCard.channel?.toLowerCase() === "whatsapp"
                                        ? isDark
                                          ? "bg-[#25D366]/15 hover:bg-[#25D366]/25 text-[#25D366] border-[#25D366]/30 shadow-sm"
                                          : "bg-[#25D366]/10 hover:bg-[#25D366]/20 text-[#128C7E] border-[#25D366]/30 shadow-xs"
                                        : isDark
                                          ? "bg-red-500/15 hover:bg-red-500/25 text-red-400 border-red-500/30 shadow-sm"
                                          : "bg-red-50 hover:bg-red-100 text-red-600 border-red-200 shadow-xs"
                                    )}
                                    title={`Open pre-filled draft in ${pCard.channel?.toLowerCase() === "whatsapp" ? "WhatsApp" : "Gmail"}`}
                                  >
                                    {pCard.channel?.toLowerCase() === "whatsapp" ? (
                                      <MessageSquare className="w-3.5 h-3.5" />
                                    ) : (
                                      <Mail className="w-3.5 h-3.5" />
                                    )}
                                    <span>Open in {pCard.channel?.toLowerCase() === "whatsapp" ? "WhatsApp" : "Gmail"}</span>
                                    <ExternalLink className="w-3 h-3 opacity-70" />
                                  </button>
                                )}
                              </div>

                              <div className="flex items-center gap-2.5">
                                {pCard.threadSearchUrl && (
                                  <button
                                    type="button"
                                    onClick={() => window.open(pCard?.threadSearchUrl!, "_blank", "noopener,noreferrer")}
                                    className={cn(
                                      "text-[11px] flex items-center gap-1 transition-colors cursor-pointer",
                                      isDark ? "text-[#94A3B8] hover:text-[#E2E8F0]" : "text-[#6B7280] hover:text-[#0A0A0A]"
                                    )}
                                    title={`View thread history in ${pCard.channel?.toLowerCase() === "whatsapp" ? "WhatsApp" : "Gmail"}`}
                                  >
                                    <span>View Thread</span>
                                    <ExternalLink className="w-3 h-3" />
                                  </button>
                                )}

                                <button
                                  type="button"
                                  onClick={() => {
                                    const draftText = activeDraftBody ? encodeURIComponent(activeDraftBody) : "";
                                    const baseTarget = pCard?.targetUrl || `/inbox?thread=case-${pCard?.caseId || ""}`;
                                    const urlWithDraft = draftText && !baseTarget.includes("draft=")
                                      ? `${baseTarget}${baseTarget.includes("?") ? "&" : "?"}draft=${draftText}`
                                      : baseTarget;
                                    handleNavigate(urlWithDraft);
                                  }}
                                  className={cn(
                                    "text-[11px] flex items-center gap-1 transition-colors cursor-pointer",
                                    isDark ? "text-[#888888] hover:text-[#FFFFFF]" : "text-[#6B7280] hover:text-[#0A0A0A]"
                                  )}
                                >
                                  <span>Open in Inbox</span>
                                  <ExternalLink className="w-3 h-3" />
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })()
                    )}
                        </div>
                      ))}
                    </div>
                  );
                })()}

              </div>

              {/* Action Buttons for Assistant Proposals (Filtered to prevent duplicates) */}
              {msg.actions && msg.actions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-1">
                  {msg.actions
                    .filter((act, idx, arr) =>
                      arr.findIndex((a) => a.label === act.label || (act.payload && a.payload === act.payload)) === idx
                    )
                    .filter((act) => {
                      if (msg.previewCard && act.actionType === "navigate") {
                        if (act.label.toLowerCase().includes("money") && msg.previewCard.type === "financial_item") return false;
                        if (act.label.toLowerCase().includes("maintenance") && msg.previewCard.type === "case_summary") return false;
                        if (act.label.toLowerCase().includes("inbox") && msg.previewCard.type === "draft_message") return false;
                        if (act.label.toLowerCase().includes("approvals") && msg.previewCard.type === "draft_message") return false;
                      }
                      return true;
                    })
                    .map((act, idx) => {
                      const isMemApprove = act.actionType === "approve_memory";
                      const isMemActivating = isMemApprove && approvingMemoryId === act.payload;
                      const isMemActivated = isMemApprove && (approvedMemoryIds.has(act.payload) || (msg.previewCard?.actionId && approvedMemoryIds.has(msg.previewCard.actionId)));

                      if (isMemActivated) {
                        return (
                          <button
                            key={idx}
                            type="button"
                            disabled
                            className="px-3 py-1.5 rounded-[8px] text-[12px] font-semibold flex items-center gap-1.5 bg-[#0F291E] border border-emerald-500/30 text-emerald-400 cursor-default"
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Rule Activated</span>
                          </button>
                        );
                      }

                      return (
                        <button
                          key={idx}
                          type="button"
                          onClick={() => handleActionClick(act)}
                          disabled={isMemActivating}
                          className={cn(
                            "px-3 py-1.5 rounded-[8px] text-[12px] font-semibold transition-colors flex items-center gap-1.5 cursor-pointer shadow-xs disabled:opacity-50",
                            act.isPrimary
                              ? "bg-[#F25C05] hover:bg-[#d94f00] text-[#FFFFFF]"
                              : isDark
                                ? "bg-[#181818] hover:bg-[#222222] border border-[#262626] text-[#FFFFFF]"
                                : "bg-[#FFFFFF] hover:bg-[#F0F0EE] border border-[#E8E8E5] text-[#0A0A0A]"
                          )}
                        >
                          {isMemActivating ? (
                            <>
                              <Loader2 className="w-3 h-3 animate-spin" />
                              <span>Activating...</span>
                            </>
                          ) : (
                            <>
                              <span>{act.label}</span>
                              <CornerDownRight className="w-3 h-3" />
                            </>
                          )}
                        </button>
                      );
                    })}
                </div>
              )}

              {msg.debugInfo && (
                <div className={cn("flex items-center gap-1.5 px-1 text-[9.5px] font-mono", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                  <span className={cn(
                    "px-1.5 py-0.5 rounded border",
                    isDark ? "bg-[#14181B] border-[#20262B] text-[#94A3B8]" : "bg-[#F0F0EE] border-[#E8E8E5] text-[#6B7280]"
                  )}>
                    stage: {msg.debugInfo.pipeline_stage}
                  </span>
                  {msg.debugInfo.fallback_reason && (
                    <span className="text-amber-600 font-semibold">
                      ⚠️ {msg.debugInfo.fallback_reason}
                    </span>
                  )}
                </div>
              )}

              <span className={cn("text-[10px] font-mono px-1", isDark ? "text-[#666666]" : "text-[#9CA3AF]")}>
                {msg.timestamp}
              </span>
            </div>
          ))}

          {/* Animated 3-dot Typing Indicator */}
          {isTyping && (
            <div className={cn(
              "flex items-center gap-1.5 p-3 rounded-[12px] border w-fit",
              isDark ? "bg-[#14181B] border-[#20262B] text-[#888888]" : "bg-[#FFFFFF] border-[#E8E8E5] text-[#6B7280] shadow-xs"
            )}>
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.15s]" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.3s]" />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 3. Suggested Chips: Streamlined minimal pills, no heavy container */}
        <div className={cn(
          "px-4 sm:px-5 py-2 border-t flex-shrink-0 transition-colors",
          isDark ? "border-[#1A1F24] bg-[#0E1113]" : "border-[#E8E8E5] bg-[#FFFFFF]"
        )}>
          <div className="flex flex-wrap gap-1.5">
            {suggestedChips.slice(0, 3).map((chip: string, idx: number) => (
              <button
                key={idx}
                onClick={() => handleSendQuery(chip)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1 rounded-full border text-[11px] transition-colors cursor-pointer",
                  isDark
                    ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] hover:border-[#334155] text-[#94A3B8] hover:text-[#FFFFFF]"
                    : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#374151] hover:text-[#0A0A0A]"
                )}
              >
                <span>{chip}</span>
                <ArrowUpRight className={cn("w-3 h-3", isDark ? "text-[#64748B]" : "text-[#9CA3AF]")} />
              </button>
            ))}
          </div>
        </div>

        {/* 4. Input Field Row: Sleek and flat */}
        <div className={cn(
          "p-3.5 sm:p-4 border-t flex-shrink-0 transition-colors",
          isDark ? "border-[#1A1F24] bg-[#0B0D0E]" : "border-[#E8E8E5] bg-[#FFFFFF]"
        )}>
          <div className="max-w-[760px] mx-auto w-full space-y-1.5">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendQuery(inputQuery);
              }}
              className="relative flex items-center"
            >
              <input
                ref={inputRef}
                type="text"
                value={inputQuery}
                onChange={(e) => setInputQuery(e.target.value)}
                placeholder="Ask Super Agent across portfolio, maintenance, arrears..."
                className={cn(
                  "w-full h-10 pl-3.5 pr-11 rounded-[10px] border text-[13px] transition-colors focus:outline-none",
                  isDark
                    ? "bg-[#14181C] border-[#222830] text-[#FFFFFF] placeholder:text-[#64748B] focus:border-[#4B5563]"
                    : "bg-[#F6F6F4] border-[#E8E8E5] text-[#0A0A0A] placeholder:text-[#9CA3AF] focus:border-[#0A0A0A]"
                )}
              />
              <button
                type="submit"
                disabled={!inputQuery.trim() || isTyping}
                className="absolute right-1.5 w-7 h-7 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] disabled:opacity-30 text-[#FFFFFF] flex items-center justify-center transition-colors cursor-pointer"
                title="Send query"
              >
                <Send className="w-3.5 h-3.5 stroke-[2.4]" />
              </button>
            </form>

            <p className={cn("text-[10px] text-center leading-tight", isDark ? "text-[#475569]" : "text-[#9CA3AF]")}>
              Autonomous planning with explicit confirmation before dispatch.
            </p>
          </div>
        </div>
      </div>
    </div>
  </aside>
    </>
  );
}



// Clean developer debugging, audit logs, and raw message dumps from card text
function cleanCardBody(body?: string | null): string {
  if (!body) return "";
  let clean = body;
  // 1. Strip developer audit logs like [Action Taken: ...]
  clean = clean.replace(/\[Action Taken:[\s\S]*?\]/gi, "");
  // 2. Strip recent messages trailer like | Recent messages: ...
  if (clean.includes(" | Recent messages:")) {
    clean = clean.split(" | Recent messages:")[0];
  }
  // 3. Strip any inline [dd Mmm hh:mm Inbound/Outbound...]: "..."
  clean = clean.replace(/\[\d{1,2}\s+[A-Za-z]{3}\s+\d{1,2}:\d{2}\s+(Inbound|Outbound)[^\]]*\]:?\s*(\"[^\"]*\"|'[^']*'|[^;\]]*)/gi, "");
  // 4. Strip tool chatter prefixes
  clean = clean.replace(/^(\s*Opening (cases|inbox|maintenance|money|properties|calendar|documents|approvals)\.?)+/gi, "");
  // 5. Strip leftover trailing delimiters like | or ; or quotes
  clean = clean.replace(/[\s|;\"]+$/g, "");
  // 6. Collapse extra whitespace
  clean = clean.replace(/\s+/g, " ").trim();
  return clean;
}

// Resolve contractor name cleanly
function resolveContractorName(card?: any): string | null {
  if (!card) return null;
  const raw = card.contractor?.trim();
  if (raw && raw !== "Assigned Contractor" && raw !== "Contractor" && !raw.startsWith("Assigned")) {
    return raw;
  }
  const fullText = `${card.title || ""} ${card.body || ""}`.toLowerCase();
  if (fullText.includes("kevin") || fullText.includes("van dijk") || fullText.includes("plumber")) {
    return "Kevin van Dijk (Plumber)";
  }
  if (fullText.includes("vermeer") || fullText.includes("electrician")) {
    return "Vermeer Elektrotechniek";
  }
  return null;
}

// Filter execution steps to prevent developer chatter or truncated answers leaking
function filterValidSteps(steps?: string[]): string[] {
  if (!steps || !steps.length) return [];
  return steps.filter((st) => {
    const s = st.trim();
    if (!s) return false;
    if (/embedding|postgres|chunks|dim|rag|memory_items|document_chunks/i.test(s)) return false;
    if (/^(opening|reading|fetching|querying|searching|checking)\b/i.test(s)) return false;
    if (/^first,\s/i.test(s) || /^based on\b/i.test(s) || /^open tasks:/i.test(s)) return false;
    if (s.length > 70) return false;
    return true;
  });
}

function formatMarkdown(text: string, isDark: boolean = false): string {
  if (!text) return "";
  let clean = text
    // Strip leading tool chatter e.g. "Opening cases.", "Opening inbox."
    .replace(/^(Opening (cases|inbox|maintenance|money|properties|calendar|documents|approvals)\.?\s*)+/gi, "")
    .trim();

  // 1. Clean up excessively long database UUIDs: Case 01a18179-777e-7370-ac07-2a83c3dfddff -> Ticket #01a181
  clean = clean.replace(/\b(?:case\s+)?([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "#$1");

  // 2. Markdown links: [Label](url) -> clean clickable anchor tag
  clean = clean.replace(
    /\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-amber-600 hover:underline font-medium inline-flex items-center gap-1 break-all">$1 ↗</a>'
  );

  // 3. Ticket references: #01a181 (BEFORE any HTML tags with hex colors are injected)
  const ticketClass = isDark
    ? "text-sky-300 bg-sky-500/15 border-sky-500/30"
    : "text-sky-800 bg-sky-50 border-sky-200";
  clean = clean.replace(
    /(#[0-9a-f]{6,8})\b/gi,
    `<span class="font-mono text-[11px] font-semibold ${ticketClass} px-1.5 py-0.5 rounded border inline-block">$1</span>`
  );

  // 4. Currency amounts: €650 or € 650,00 -> monospace tabular-nums pill
  const currClass = isDark
    ? "text-emerald-300 bg-emerald-500/15 border-emerald-500/30"
    : "text-emerald-800 bg-emerald-50 border-emerald-200";
  clean = clean.replace(
    /(€\s?\d+(?:[.,]\d+)?)/g,
    `<span class="font-mono tabular-nums font-semibold ${currClass} px-1.5 py-0.5 rounded border text-[12px] inline-block">$1</span>`
  );

  // 5. Inline backticks: `code`
  const codeClass = isDark
    ? "bg-[#181D22] text-[#E2E8F0] border-[#262F38]"
    : "bg-[#F3F4F6] text-[#1F2937] border-[#E5E7EB]";
  clean = clean.replace(
    /`([^`]+)`/g,
    `<code class="px-1.5 py-0.5 rounded font-mono text-[12px] break-all border ${codeClass}">$1</code>`
  );

  // 6. Bold: **text**
  const boldClass = isDark ? "text-[#FFFFFF]" : "text-[#0A0A0A]";
  clean = clean.replace(/\*\*(.*?)\*\*/g, `<strong class="${boldClass} font-semibold">$1</strong>`);

  // 7. Italics: *text*
  const italicClass = isDark ? "text-[#CCCCCC]" : "text-[#4B5563]";
  clean = clean.replace(/\*(.*?)\*/g, `<em class="${italicClass}">$1</em>`);

  // 8. Structured Headings: ### Header
  const headingClass = isDark ? "text-[#94A3B8]" : "text-[#374151]";
  clean = clean.replace(
    /^###\s+(.*?)$/gm,
    `<div class="text-[11.5px] font-semibold uppercase tracking-wider ${headingClass} mt-3 mb-1.5 flex items-center gap-1.5"><span class="w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0"></span><span>$1</span></div>`
  );

  // 9. Executive Callout Quotes: Group contiguous blockquote lines into a single cohesive card
  const quoteBoxClass = isDark
    ? "border-amber-500/80 bg-amber-500/10 text-[#E2E8F0]"
    : "border-amber-500/80 bg-amber-50/70 text-[#1E293B]";
  clean = clean.replace(
    /(?:^>[ \t]?[^\n]*(?:\r?\n|$))+/gm,
    (block) => {
      const lines = block
        .trimEnd()
        .split(/\r?\n/)
        .map((l) => l.replace(/^>[ \t]?/, ""))
        .join("\n")
        .trim();
      return `<div class="border-l-2 ${quoteBoxClass} px-3.5 py-2.5 rounded-r-[8px] my-2.5 text-[12.5px] leading-relaxed font-normal">\n${lines}\n</div>`;
    }
  );

  // 10. Numbered Step Lists: 1. ...
  const numBadgeClass = isDark
    ? "bg-[#20272F] text-[#94A3B8]"
    : "bg-[#E5E7EB] text-[#374151]";
  clean = clean.replace(
    /^(\d+)\.\s+(.*?)$/gm,
    `<div class="flex items-start gap-2.5 my-1.5"><span class="flex items-center justify-center w-4 h-4 rounded-full ${numBadgeClass} text-[10px] font-semibold shrink-0 mt-0.5">$1</span><span class="break-words min-w-0 flex-1">$2</span></div>`
  );

  // 11. Bullet list: • or - (Using CSS class text-amber-500 rather than hex literal so no regex ever collides)
  clean = clean.replace(
    /^([•\-])\s+(.*?)$/gm,
    '<div class="flex items-start gap-2 my-1"><span class="text-amber-500 font-bold shrink-0">•</span><span class="break-words min-w-0 flex-1">$2</span></div>'
  );

  return clean;
}
