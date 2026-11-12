"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Calendar,
  Sparkles,
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
  FileText,
  History,
  Plus,
  Pin,
  Trash2,
  Sun,
  Moon,
  UserRound,
  ArrowUp,
  ThumbsUp,
  ThumbsDown,
  MoreVertical,
  List,
  Mic,
  MicOff,
  X,
  Home,
  Search,
  Pencil,
  ChevronDown,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { askAgent, approveInboxDraft, approveStandingRule, AssistantCard, CardAction, PreviewCardData, updateAgentConversation, getInboxThreads } from "@/lib/api";
import { InboxThread } from "@/types/inbox";
import { formatClock } from "@/lib/clock";

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
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { TranslationToggle } from "@/components/inbox/TranslationToggle";
import { useLanguage } from "@/context/LanguageContext";
import { BACKEND_BASE_URL, apiFetch } from "@/lib/backend";

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
  const { t, language } = useLanguage();
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
  const [showFewerSuggestions, setShowFewerSuggestions] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [selectedPriorityFilter, setSelectedPriorityFilter] = useState<string>("All Priorities");
  const [selectedChannelFilter, setSelectedChannelFilter] = useState<string>("All Message Type");
  const [isPriorityModalOpen, setIsPriorityModalOpen] = useState(false);
  const [isChannelModalOpen, setIsChannelModalOpen] = useState(false);
  const [expandedCardIds, setExpandedCardIds] = useState<Record<string, boolean>>({});
  const [liveThreads, setLiveThreads] = useState<InboxThread[]>([]);

  useEffect(() => {
    getInboxThreads({}).then((res) => {
      if (res && Array.isArray(res.threads)) {
        setLiveThreads(res.threads);
      }
    }).catch(() => {});
  }, []);

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
  const handleSendQueryRef = useRef<(q: string) => void>(() => {});
  const {
    isListening,
    isPausing: isPausingToAutoSend,
    error: voiceError,
    speechLang,
    setSpeechLang,
    startListening,
    stopListening,
    toggleVoiceInput: toggleVoice,
    cancelPause,
  } = useVoiceInput({
    initialLang: "en",
    silenceTimeoutMs: 1800, // after 1.8s of silence the spoken question is sent on its own
    onTranscript: (text) => setInputQuery(text),
    onSilencePause: (text) => {
      const queryToSend = text.trim();
      if (queryToSend) {
        setInputQuery("");
        handleSendQueryRef.current(queryToSend);
      }
    },
  });

  // Typing cancels a pending auto-send; the shared hook owns the recognition session itself.
  const cancelAutoSend = cancelPause;

  const toggleVoiceInput = (overrideLang?: "en" | "nl") => toggleVoice(inputQuery, overrideLang);

  const handleToggleLang = () => {
    const nextLang = speechLang === "nl" ? "en" : "nl";
    setSpeechLang(nextLang);
    if (isListening) {
      stopListening();
      setTimeout(() => startListening(inputQuery, nextLang), 100);
    }
  };

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
          : `${BACKEND_BASE_URL}${action.endpoint}`;
        const res = await apiFetch(fullUrl, {
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
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
        "Which emails urgent",
      ];
    }
    if (currentPageName.toLowerCase().includes("contact")) {
      return [
        "Generate reply for latest email",
        "Summarise unread messages",
        "Draft WhatsApp update",
        "Check lease renewal & rent status",
      ];
    }
    if (currentPageName.toLowerCase().includes("money")) {
      return [
        "Why is the invoice open?",
        "Match open payments",
        "Who is behind on rent?",
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
      "What should I do first?",
      "Who is behind on rent?",
      "Show active leases",
    ];
  }, [lastAssistantMsg, currentPageName]);

  const handleSendQuery = async (queryText: string) => {
    const trimmed = queryText.trim();
    if (!trimmed) return;

    const userMsg: AssistantMessage = {
      id: `user-${Date.now()}`,
      sender: "user",
      timestamp: formatClock(new Date()),
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
        timestamp: formatClock(new Date()),
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
        timestamp: formatClock(new Date()),
        text: "I was unable to complete your request right now. Please verify the backend connection and try again.",
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  handleSendQueryRef.current = handleSendQuery;

  const handleApproveCalendar = async (cardId: string, eventId?: string | null, payloadUrl?: string | null) => {
    setApprovingCalendarId(cardId);
    try {
      const url = payloadUrl || `/api/calendar/events/${eventId}/approve`;
      const fullUrl = url.startsWith("http") ? url : `${BACKEND_BASE_URL}${url}`;
      const res = await apiFetch(fullUrl, { method: "POST", headers: { "Content-Type": "application/json" } });
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
        const fullUrl = payloadUrl.startsWith("http") ? payloadUrl : `${BACKEND_BASE_URL}${payloadUrl}`;
        await apiFetch(fullUrl, {
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
    // Disambiguate /messages -> /inbox so code never breaks
    let target = url;
    if (target === "/messages" || target.startsWith("/messages?")) {
      target = target.replace("/messages", "/inbox");
    }
    // Only yield/close if in center modal mode OR if navigating to an item that opens a right drawer
    const opensDrawer = target.includes("ticket=") || target.includes("invoice=") || target.includes("tx=") || target.includes("thread=");
    if (panelMode === "center" || opensDrawer) {
      onClose();
    }
    // Perform client-side Next.js navigation without hard-reloading the browser or wiping state
    router.push(target);
    // Dispatch instant sync event for same-page transitions
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("estateos:navigate", { detail: { url: target } }));
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





  // Conversations list for mobile drawer (falls back to mockup reference items if none in state)
  const displayConversations = React.useMemo(() => {
    if (superAgent.conversations && superAgent.conversations.length > 0) {
      return superAgent.conversations.map((c) => ({
        id: c.id,
        title: c.title || "Untitled Chat",
        date: c.last_turn_at
          ? new Date(c.last_turn_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })
          : "Today",
      }));
    }
    return [
      { id: "conv-1", title: "Create draft approval message", date: "12 Oct" },
      { id: "conv-2", title: "Ticket raised issues", date: "11 Oct" },
    ];
  }, [superAgent.conversations]);

  if (!isOpen) return null;

  return (
    <>
      {/* ============================================================== */}
      {/* MOBILE SUPER AGENT (100% matched to reference image design)    */}
      {/* Activates exclusively on mobile screens (md:hidden)           */}
      {/* ============================================================== */}
      <div className="md:hidden fixed inset-0 z-50 bg-[#05070e] flex flex-col justify-between overflow-hidden text-white font-sans select-text">
        {/* Glowing Turquoise & Blue Aurora Backdrop (Exact radiant aura from mockup) */}
        <div
          className="absolute -top-[12%] -left-[15%] w-[130%] h-[60%] pointer-events-none"
          style={{
            background: "radial-gradient(ellipse 85% 65% at 20% 15%, #00e5ff 0%, #1d4ed8 48%, #05070e 85%, transparent 100%)",
            filter: "blur(48px)",
            opacity: 0.9,
          }}
        />
        <div
          className="absolute top-0 right-0 w-[85%] h-[42%] pointer-events-none"
          style={{
            background: "radial-gradient(circle at 85% 15%, #2563eb 0%, transparent 70%)",
            filter: "blur(55px)",
            opacity: 0.65,
          }}
        />
        {/* Subtle dark texture overlay */}
        <div className="absolute inset-0 bg-[radial-gradient(#ffffff0a_1px,transparent_1px)] [background-size:18px_18px] pointer-events-none opacity-40" />

        {/* Top Navigation Bar: Unified Single Row Header */}
        <div className="relative z-10 pt-[max(env(safe-area-inset-top),14px)] px-5 pb-2 shrink-0">
          <div className="flex items-center justify-between gap-3">
            {/* Left: 3-bar Hamburger (Opens History Drawer) */}
            <button
              type="button"
              onClick={() => setIsMobileMenuOpen(true)}
              className="flex flex-col gap-1 p-1 text-white hover:opacity-80 transition-opacity cursor-pointer shrink-0"
              title="Menu & Conversation History"
            >
              <span className="w-4.5 h-[2px] bg-white rounded-full"></span>
              <span className="w-3.5 h-[2px] bg-white rounded-full"></span>
              <span className="w-4 h-[2px] bg-white rounded-full"></span>
            </button>

            {/* Center: Dynamic Executive Co-Pilot Status */}
            <div className="flex items-center gap-2 min-w-0">
              <div className="w-6 h-6 rounded-full bg-cyan-500/20 text-cyan-400 flex items-center justify-center shadow-[0_0_10px_rgba(0,229,255,0.4)] shrink-0">
                <Sparkles className="w-3.5 h-3.5 animate-pulse" />
              </div>
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-[13.5px] font-semibold text-white tracking-tight truncate">
                  Executive Copilot
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#00e5ff] animate-pulse shadow-[0_0_8px_#00e5ff] shrink-0" />
              </div>
            </div>

            {/* Right: + New & Close (X) Buttons together in the same row */}
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={superAgent.startNewChat}
                className="text-[11px] font-medium text-slate-200 hover:text-white px-2.5 py-1 rounded-full bg-white/10 hover:bg-white/20 border border-white/10 flex items-center gap-1 transition-colors cursor-pointer"
                title="Start a new chat"
              >
                <Plus className="w-3 h-3 stroke-[2.5]" />
                <span>New</span>
              </button>

              <button
                type="button"
                onClick={onClose}
                className="w-7 h-7 rounded-full bg-white/10 hover:bg-white/20 text-white/80 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
                title="Close Super Agent"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* Mobile Main Body: Hero Greeting & Reticle OR Active Conversation Stream */}
        {messages.length <= 1 ? (
          <div className="relative z-10 flex-1 flex flex-col justify-between px-6 pt-8 pb-3 overflow-y-auto">
            {/* Hero Greeting Headline */}
            <div>
              <h1 className="text-[35px] font-bold text-white tracking-tight leading-[1.18] font-sans">
                Hello Harjhot<br />
                How can I help you<br />
                today?
              </h1>
            </div>

            {/* Centered Ambient Glowing Cyan Reticle */}
            <div className="my-auto py-8 flex items-center justify-center relative w-full">
              <div className="w-full flex items-center justify-center relative">
                <div className="flex-1 border-t border-dashed border-[#00e5ff]/50"></div>
                <div className="relative mx-3 flex items-center justify-center">
                  <div className="w-7 h-7 flex items-center justify-center relative">
                    <div className="absolute w-full h-[1.5px] border-t border-dashed border-[#00e5ff]/70"></div>
                    <div className="absolute h-full w-[1.5px] border-l border-dashed border-[#00e5ff]/70"></div>
                    <div className="w-1.5 h-1.5 rounded-full bg-[#00e5ff] shadow-[0_0_12px_#00e5ff,0_0_24px_#00e5ff]"></div>
                  </div>
                </div>
                <div className="flex-1 border-t border-dashed border-[#00e5ff]/50"></div>
              </div>
            </div>

            {/* Suggestions Header & Rounded Action Chips */}
            <div className="mt-auto mb-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-[#94a3b8] mb-2.5">
                <Sparkles className="w-3.5 h-3.5 text-[#94a3b8] fill-[#94a3b8]" />
                <span>Suggestions</span>
              </div>
              <div className="flex flex-wrap items-center gap-2.5">
                <button
                  type="button"
                  onClick={() => handleSendQuery("Check unread messages and summarize urgent ones")}
                  className="px-4 py-2 rounded-full bg-[#091526]/90 hover:bg-[#10223d] border border-[#1b3152] text-white text-xs font-medium flex items-center gap-2 shadow-sm transition-all cursor-pointer active:scale-95"
                >
                  <MessageSquare className="w-3.5 h-3.5 text-[#38bdf8]" />
                  <span>Unread Messages</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleSendQuery("Review active maintenance tickets and dispatch status")}
                  className="px-4 py-2 rounded-full bg-[#091526]/90 hover:bg-[#10223d] border border-[#1b3152] text-white text-xs font-medium flex items-center gap-2 shadow-sm transition-all cursor-pointer active:scale-95"
                >
                  <Wrench className="w-3.5 h-3.5 text-[#38bdf8]" />
                  <span>Maintenance Ticket</span>
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="relative z-10 flex-1 overflow-y-auto px-4 py-3 space-y-3.5">
            {messages.slice(1).map((m) => (
              <div key={m.id} className="w-full">
                {m.sender === "user" ? (
                  <div className="ml-auto items-end flex flex-col max-w-[85%] text-[13px] leading-relaxed">
                    <div className="p-3 rounded-2xl shadow-md bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-br-xs">
                      <p className="whitespace-pre-wrap">{m.text}</p>
                    </div>
                    <span className="text-[10px] text-white/40 mt-1 px-1">{m.timestamp}</span>
                  </div>
                ) : (
                  <div className="mr-auto items-start flex flex-col w-full text-[13px] leading-relaxed space-y-3 select-text">
                    <div className="text-slate-100 leading-relaxed font-sans text-[13.5px] select-text">
                      <p className="whitespace-pre-wrap">
                        {m.text.includes("matching conversation")
                          ? "I found unread messages today across WhatsApp and Gmail. Showing the latest messages requiring your immediate action:"
                          : m.text}
                      </p>
                    </div>

                    {/* Filter Pills & Interactive Cards (Matches Mockup) */}
                    {(() => {
                      const rawCards = (m.previewCards && m.previewCards.length > 0)
                        ? m.previewCards
                        : (m.previewCard ? [m.previewCard] : []);

                      // Find the user query that directly triggered this assistant turn
                      const prevUserMsg = [...messages.slice(0, messages.indexOf(m))]
                        .reverse()
                        .find((item) => item.sender === "user")?.text.toLowerCase() || "";

                      // Only trigger unread cards if the user specifically asked for messages/unread, or if backend returned retrieval matches
                      const isUnreadQuery =
                        /unread|messages|inbox|conversations/i.test(prevUserMsg) ||
                        m.text.toLowerCase().includes("matching conversation") ||
                        m.text.toLowerCase().includes("found unread messages");

                      const isGeneralHelpQuery = /what (can|u can) do|who are you|hello|hi\b/i.test(prevUserMsg);

                      const mappedLive: PreviewCardData[] = (liveThreads && liveThreads.length > 0)
                        ? liveThreads.slice(0, 3).map((t) => {
                            const isCrit = t.urgency === "emergency" || t.urgency === "high";
                            return {
                              type: "case_summary",
                              actionId: t.id,
                              caseId: t.ticketNumber || t.caseRef,
                              title: t.senderName,
                              subtitle: t.latestSnippet || t.caseSummary || "",
                              recipient: t.senderName,
                              unitLabel: t.unitLabel || "Centrum Portfolio",
                              body: t.latestSnippet || t.caseSummary || "No recent snippet available",
                              badgeLabel: isCrit ? "Critical" : "Normal",
                              badgeColor: isCrit ? "rose" : "blue",
                              channel: t.channel || "whatsapp",
                              subject: t.subject || "Direct Message",
                              status: isCrit ? "Critical" : "Normal",
                            };
                          })
                        : [];

                      const cardsList: PreviewCardData[] = rawCards.length > 0
                        ? rawCards
                        : (isUnreadQuery && !isGeneralHelpQuery)
                        ? (mappedLive.length > 0
                            ? mappedLive
                            : [
                                {
                                  type: "case_summary",
                                  actionId: "msg-praveen",
                                  caseId: "case-praveen",
                                  title: "Praveen Rostova",
                                  subtitle: "Emergency kitchen drain pipe rupture detected beneath the sink unit; active water is pooling rapidly onto the oak hardwood floor",
                                  recipient: "Praveen Rostova",
                                  unitLabel: "Unit 4B · Parkview Residencies",
                                  body: "Emergency kitchen drain pipe rupture detected beneath the sink unit; active water is pooling rapidly onto the oak hardwood floor",
                                  badgeLabel: "Critical",
                                  badgeColor: "rose",
                                  channel: "whatsapp",
                                  subject: "Emergency Kitchen Drain Leak",
                                  status: "Critical",
                                },
                                {
                                  type: "case_summary",
                                  actionId: "msg-elena",
                                  caseId: "case-elena",
                                  title: "Elena Rostova",
                                  subtitle: "Inquiry regarding formal 12-month lease renewal starting January 1st, 2027; tenant accepts the proposed +4.0% market rate",
                                  recipient: "Elena Rostova",
                                  unitLabel: "Unit 4B · Parkview Residencies",
                                  body: "Inquiry regarding formal 12-month lease renewal starting January 1st, 2027; tenant accepts the proposed +4.0% market rate",
                                  badgeLabel: "Critical",
                                  badgeColor: "rose",
                                  channel: "gmail",
                                  subject: "Lease renewal inquiry",
                                  status: "Critical",
                                },
                              ])
                        : [];

                      if (cardsList.length === 0) return null;

                      const filtered = cardsList.filter((card) => {
                        if (selectedPriorityFilter !== "All Priorities") {
                          const cardPriority = (card.badgeLabel || card.status || "Normal").toLowerCase();
                          if (!cardPriority.includes(selectedPriorityFilter.toLowerCase())) return false;
                        }
                        if (selectedChannelFilter !== "All Message Type") {
                          const cardChan = (card.channel || "").toLowerCase();
                          if (!cardChan.includes(selectedChannelFilter.toLowerCase())) return false;
                        }
                        return true;
                      });

                      return (
                        <div className="w-full space-y-3 pt-1">
                          {/* Filter Pills Row */}
                          <div className="flex items-center gap-2 pt-1 pb-1">
                            <button
                              type="button"
                              onClick={() => setIsPriorityModalOpen(true)}
                              className="px-3.5 py-1.5 rounded-full bg-[#0E2138] border border-[#162B45] text-xs font-medium text-slate-300 flex items-center gap-1.5 hover:text-white transition-colors cursor-pointer"
                            >
                              <span>{selectedPriorityFilter}</span>
                              <ChevronDown className="w-3.5 h-3.5 opacity-60" />
                            </button>
                            <button
                              type="button"
                              onClick={() => setIsChannelModalOpen(true)}
                              className="px-3.5 py-1.5 rounded-full bg-[#0E2138] border border-[#162B45] text-xs font-medium text-slate-300 flex items-center gap-1.5 hover:text-white transition-colors cursor-pointer"
                            >
                              <span>{selectedChannelFilter}</span>
                              <ChevronDown className="w-3.5 h-3.5 opacity-60" />
                            </button>
                          </div>

                          {/* Cards List */}
                          <div className="space-y-3">
                            {filtered.map((card, cIdx) => {
                              const cardKey = card.actionId || card.caseId || `card-${cIdx}`;
                              const senderName = card.recipient || card.title || "Tenant Contact";
                              const unitText = card.unitLabel || "Centrum Portfolio";
                              const priority = card.badgeLabel || "Critical";
                              const isCritical = priority.toLowerCase().includes("critical") || priority.toLowerCase().includes("urgent");
                              const channel = (card.channel || "whatsapp").toLowerCase();
                              const isWhatsApp = channel.includes("whatsapp");
                              const isExpanded = expandedCardIds[cardKey];
                              const bodyText = card.body || card.subtitle || card.title || "";
                              const isLong = bodyText.length > 90;

                              return (
                                <div
                                  key={cardKey}
                                  className="p-4 rounded-2xl bg-[#0E2138]/95 border border-[#162B45] space-y-3 shadow-md"
                                >
                                  {/* Header: Avatar, Name, Unit, Timestamp, Priority Badge */}
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="flex items-center gap-2.5">
                                      <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-slate-700 to-slate-600 flex items-center justify-center font-semibold text-xs text-white shrink-0">
                                        {senderName.slice(0, 2).toUpperCase()}
                                      </div>
                                      <div>
                                        <div className="font-semibold text-sm text-white">{senderName}</div>
                                        <div className="text-[11px] text-slate-400">{unitText}</div>
                                      </div>
                                    </div>

                                    <div className="flex flex-col items-end gap-1 shrink-0">
                                      <span className="text-[11px] text-slate-500">18h ago</span>
                                      <span
                                        className={cn(
                                          "text-[11px] font-semibold",
                                          isCritical ? "text-[#ef4444]" : "text-emerald-400"
                                        )}
                                      >
                                        {priority}
                                      </span>
                                    </div>
                                  </div>

                                  {/* Message Body with Show More */}
                                  <div className="text-[13px] leading-relaxed text-slate-200">
                                    <span>{isExpanded || !isLong ? bodyText : `${bodyText.slice(0, 90)}... `}</span>
                                    {isLong && (
                                      <button
                                        type="button"
                                        onClick={() => setExpandedCardIds((prev) => ({ ...prev, [cardKey]: !prev[cardKey] }))}
                                        className="text-cyan-400 font-medium hover:underline ml-1 cursor-pointer"
                                      >
                                        {isExpanded ? "Show less" : "Show more"}
                                      </button>
                                    )}
                                  </div>

                                  {/* Action Buttons: Reply, Forward, and Channel Badge */}
                                  <div className="flex items-center justify-between pt-1 border-t border-white/5 text-xs">
                                    <div className="flex items-center gap-4">
                                      <button
                                        type="button"
                                        onClick={() => {
                                          if (isWhatsApp) {
                                            const phone = (card as any).phone || "+31688123456";
                                            window.open(`https://wa.me/${phone.replace(/[^0-9]/g, "")}?text=${encodeURIComponent(bodyText)}`, "_blank");
                                          } else {
                                            const email = (card as any).email || "vipint9902@gmail.com";
                                            window.open(`https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(email)}&su=${encodeURIComponent("Re: " + (card.subject || "Message"))}&body=${encodeURIComponent(bodyText)}`, "_blank");
                                          }
                                        }}
                                        className="flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 font-medium cursor-pointer"
                                      >
                                        <CornerDownRight className="w-3.5 h-3.5" />
                                        <span>Reply</span>
                                      </button>

                                      <button
                                        type="button"
                                        onClick={() => {
                                          if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                                            navigator.clipboard.writeText(bodyText);
                                          }
                                        }}
                                        className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 font-medium cursor-pointer"
                                      >
                                        <SendHorizontal className="w-3.5 h-3.5" />
                                        <span>Forward</span>
                                      </button>
                                    </div>

                                    <div className="flex items-center gap-1.5 text-slate-400 text-xs">
                                      {isWhatsApp ? (
                                        <>
                                          <MessageSquare className="w-3.5 h-3.5 text-[#25D366]" />
                                          <span>WhatsApp</span>
                                        </>
                                      ) : (
                                        <>
                                          <Mail className="w-3.5 h-3.5 text-[#EA4335]" />
                                          <span>Gmail</span>
                                        </>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })()}

                    <span className="text-[10px] text-white/40 mt-1 px-1">{m.timestamp}</span>
                  </div>
                )}
              </div>
            ))}
            {isTyping && (
              <div className="flex items-center gap-2 text-xs text-cyan-300 py-1">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Super Agent is thinking...</span>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}

        {/* Floating Voice & Text Dock (Without + button; New Chat is in the drawer) */}
        <div className="relative z-10 px-4 pb-[max(env(safe-area-inset-bottom),16px)] pt-1 shrink-0">
          <div className="bg-[#0A1B2F]/95 backdrop-blur-2xl border border-[#162B45] rounded-2xl p-3 shadow-[0_12px_36px_rgba(0,0,0,0.8)]">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendQuery(inputQuery);
              }}
              className="flex flex-col gap-2"
            >
              <textarea
                rows={1}
                value={inputQuery}
                onChange={(e) => {
                  cancelAutoSend();
                  setInputQuery(e.target.value);
                }}
                onKeyDown={(e) => {
                  cancelAutoSend();
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendQuery(inputQuery);
                  }
                }}
                placeholder="Talk to your super agent and get your job done"
                className="w-full text-[13px] bg-transparent outline-none resize-none text-white placeholder:text-slate-500 leading-normal"
              />
              <div className="flex items-center justify-between pt-1">
                {/* Left: Language selector & Listening status */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleToggleLang}
                    className={cn(
                      "text-[11px] font-semibold px-2.5 py-1 rounded-full border transition-all cursor-pointer flex items-center gap-1 select-none",
                      speechLang === "nl"
                        ? "bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-[0_0_8px_rgba(245,158,11,0.25)]"
                        : "bg-cyan-500/20 text-cyan-300 border-cyan-500/40 shadow-[0_0_8px_rgba(0,229,255,0.25)]"
                    )}
                    title={speechLang === "nl" ? "Voice language: Nederlands (tap to switch to English)" : "Voice language: English (tap to switch to Nederlands)"}
                  >
                    <span>{speechLang === "nl" ? "🇳🇱 NL" : "🇬🇧 EN"}</span>
                  </button>

                  {isListening && (
                    <span className="text-[11px] text-cyan-300 font-medium animate-pulse flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping inline-block" />
                      {isPausingToAutoSend
                        ? "⚡ Sending..."
                        : speechLang === "nl"
                        ? "Luisteren (NL)..."
                        : "Listening (EN)..."}
                    </span>
                  )}
                  {voiceError && !isListening && (
                    <span className="text-[11px] text-amber-300 font-medium">{voiceError}</span>
                  )}
                </div>

                {/* Right: White Circular Mic Button & Send Button */}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => toggleVoiceInput()}
                    className={cn(
                      "w-9 h-9 rounded-full flex items-center justify-center transition-all cursor-pointer shadow-lg",
                      isListening
                        ? "bg-[#00e5ff] text-black shadow-[0_0_18px_#00e5ff] animate-pulse ring-2 ring-cyan-300"
                        : "bg-white text-black hover:bg-slate-100 active:scale-95"
                    )}
                    title={isListening ? "Listening... Tap to stop" : `Tap to Speak (${speechLang === "nl" ? "Dutch" : "English"})`}
                  >
                    {isListening ? (
                      <MicOff className="w-4 h-4 stroke-[2.5]" />
                    ) : (
                      <Mic className="w-4 h-4 stroke-[2.5]" />
                    )}
                  </button>
                  {/* Dark Circular Send Button */}
                  <button
                    type="submit"
                    disabled={!inputQuery.trim() || isTyping}
                    className={cn(
                      "w-8 h-8 rounded-full bg-[#2a2b31] flex items-center justify-center transition-all cursor-pointer",
                      inputQuery.trim()
                        ? "text-white hover:bg-blue-600 active:scale-95"
                        : "text-slate-500 cursor-not-allowed opacity-60"
                    )}
                    title="Send"
                  >
                    <ArrowUp className="w-4 h-4 stroke-[2.5]" />
                  </button>
                </div>
              </div>
            </form>
          </div>
          {/* iOS / Android Navigation Gesture Bar */}
          <div className="mt-2.5 flex justify-center">
            <div className="h-1 w-32 bg-white/30 rounded-full"></div>
          </div>
        </div>

        {/* ============================================================== */}
        {/* MOBILE SLIDE-OVER DRAWER (Matches uploaded UI image 100%)       */}
        {/* ============================================================== */}
        {isMobileMenuOpen && (
          <div className="absolute inset-0 z-50 bg-[#0A1B2F] flex flex-col justify-between p-6 pt-[max(env(safe-area-inset-top),20px)] pb-[max(env(safe-area-inset-bottom),20px)] animate-in fade-in slide-in-from-left-4 duration-200">
            <div>
              {/* Header: Logo [HR] RealEstate OS & Actions */}
              <div className="flex items-center justify-between pb-6">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg border border-white/20 bg-white/5 flex items-center justify-center font-bold text-xs tracking-wider text-white">
                    HR
                  </div>
                  <span className="font-bold text-[18px] text-white tracking-tight">RealEstate OS</span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setIsMobileMenuOpen(false);
                      setTimeout(() => inputRef.current?.focus(), 150);
                    }}
                    className="w-9 h-9 rounded-full bg-[#222429] hover:bg-[#2c2f36] text-white/80 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
                    title="Search"
                  >
                    <Search className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setIsMobileMenuOpen(false)}
                    className="w-9 h-9 rounded-full bg-[#222429] hover:bg-[#2c2f36] text-white/80 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
                    title="Close Menu"
                  >
                    <div className="flex flex-col gap-1">
                      <span className="w-4 h-[2px] bg-white rounded-full"></span>
                      <span className="w-3 h-[2px] bg-white rounded-full"></span>
                      <span className="w-3.5 h-[2px] bg-white rounded-full"></span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Navigation Items */}
              <nav className="space-y-4 pt-1 pb-6 border-b border-white/5">
                <button
                  type="button"
                  onClick={() => {
                    setIsMobileMenuOpen(false);
                    onClose();
                    router.push("/");
                  }}
                  className="flex items-center gap-3 text-white/90 hover:text-white text-[15px] font-medium transition-colors w-full text-left py-1 cursor-pointer"
                >
                  <Home className="w-5 h-5 text-white/70" />
                  <span>Dashboard</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsMobileMenuOpen(false);
                    onClose();
                    router.push("/contacts");
                  }}
                  className="flex items-center gap-3 text-white/90 hover:text-white text-[15px] font-medium transition-colors w-full text-left py-1 cursor-pointer"
                >
                  <UserRound className="w-5 h-5 text-white/70" />
                  <span>Contacts</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsMobileMenuOpen(false);
                    onClose();
                    router.push("/inbox");
                  }}
                  className="flex items-center gap-3 text-white/90 hover:text-white text-[15px] font-medium transition-colors w-full text-left py-1 cursor-pointer"
                >
                  <MessageSquare className="w-5 h-5 text-white/70" />
                  <span>Messages</span>
                </button>
              </nav>

              {/* Past Conversations List */}
              <div className="pt-5">
                <div className="text-[13px] font-medium text-[#64748B] mb-3">
                  Conversations
                </div>
                <div className="space-y-3.5 overflow-y-auto max-h-[46vh] pr-1">
                  {displayConversations.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => {
                        if (c.id.startsWith("conv-")) {
                          handleSendQuery(c.title);
                        } else {
                          superAgent.selectConversation(c.id);
                        }
                        setIsMobileMenuOpen(false);
                      }}
                      className="w-full flex items-center justify-between text-left text-[14px] text-white hover:text-cyan-300 transition-colors py-1 cursor-pointer group"
                    >
                      <span className="truncate pr-3 font-normal group-hover:underline">{c.title}</span>
                      <span className="text-[12px] text-[#64748B] shrink-0 font-normal">{c.date}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Bottom Bar: Profile Avatar & New Chat Blue Pill Button */}
            <div className="flex items-center justify-between pt-4 border-t border-white/5">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-amber-600 to-amber-400 flex items-center justify-center text-white font-bold text-sm shadow-sm">
                  H
                </div>
                <span className="font-semibold text-[15px] text-white">Hi, Harjhot</span>
              </div>

              <button
                type="button"
                onClick={() => {
                  superAgent.startNewChat();
                  setIsMobileMenuOpen(false);
                }}
                className="bg-[#2563eb] hover:bg-blue-600 text-white font-semibold text-xs px-4 py-2.5 rounded-full flex items-center gap-1.5 shadow-md active:scale-95 transition-all cursor-pointer"
              >
                <Pencil className="w-3.5 h-3.5" />
                <span>New Chat</span>
              </button>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* PRIORITY FILTER BOTTOM SHEET (Matches mockup image 1)          */}
        {/* ============================================================== */}
        {isPriorityModalOpen && (
          <div className="absolute inset-0 z-50 flex flex-col justify-end">
            <div
              className="absolute inset-0 bg-black/70 backdrop-blur-xs transition-opacity"
              onClick={() => setIsPriorityModalOpen(false)}
            />
            <div className="relative w-full bg-[#151619] border-t border-white/10 rounded-t-[22px] p-6 pb-[max(env(safe-area-inset-bottom),24px)] space-y-5 shadow-2xl animate-in slide-in-from-bottom duration-200">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-white tracking-tight">Priority</h3>
                <button
                  type="button"
                  onClick={() => setIsPriorityModalOpen(false)}
                  className="w-8 h-8 rounded-full bg-[#24262b] text-white/80 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                {["All Priorities", "Critical", "High", "Normal", "Low"].map((p) => {
                  const isSelected = selectedPriorityFilter === p;
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => {
                        setSelectedPriorityFilter(p);
                        setIsPriorityModalOpen(false);
                      }}
                      className={cn(
                        "px-5 py-2.5 rounded-full text-xs font-semibold transition-all cursor-pointer",
                        isSelected
                          ? "bg-[#2563eb] text-white shadow-md"
                          : "bg-[#24262b] text-slate-200 hover:bg-[#2e3137]"
                      )}
                    >
                      {p}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* MESSAGE TYPE FILTER BOTTOM SHEET                               */}
        {/* ============================================================== */}
        {isChannelModalOpen && (
          <div className="absolute inset-0 z-50 flex flex-col justify-end">
            <div
              className="absolute inset-0 bg-black/70 backdrop-blur-xs transition-opacity"
              onClick={() => setIsChannelModalOpen(false)}
            />
            <div className="relative w-full bg-[#151619] border-t border-white/10 rounded-t-[22px] p-6 pb-[max(env(safe-area-inset-bottom),24px)] space-y-5 shadow-2xl animate-in slide-in-from-bottom duration-200">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-white tracking-tight">Message Type</h3>
                <button
                  type="button"
                  onClick={() => setIsChannelModalOpen(false)}
                  className="w-8 h-8 rounded-full bg-[#24262b] text-white/80 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                {["All Message Type", "WhatsApp", "Gmail"].map((chan) => {
                  const isSelected = selectedChannelFilter === chan;
                  return (
                    <button
                      key={chan}
                      type="button"
                      onClick={() => {
                        setSelectedChannelFilter(chan);
                        setIsChannelModalOpen(false);
                      }}
                      className={cn(
                        "px-5 py-2.5 rounded-full text-xs font-semibold transition-all cursor-pointer",
                        isSelected
                          ? "bg-[#2563eb] text-white shadow-md"
                          : "bg-[#24262b] text-slate-200 hover:bg-[#2e3137]"
                      )}
                    >
                      {chan}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ============================================================== */}
      {/* DESKTOP SUPER AGENT (100% original layout on md: and larger)   */}
      {/* ============================================================== */}
      <aside
        id="aiSidePanel"
        className={cn(
          "hidden md:flex bg-white flex-col justify-between font-sans shrink-0 overflow-hidden relative transition-all duration-300",
          isFullScreen
            ? "absolute inset-0 z-30 m-0 mr-[10px] mb-[10px] h-[calc(100%-10px)] rounded-[14px] border border-[#162B45] shadow-[0_2px_8px_rgba(0,0,0,0.2)] animate-in fade-in duration-200"
            : "fixed inset-0 z-50 md:relative md:inset-auto md:z-10 w-full md:w-[420px] xl:w-[450px] shrink-0 m-0 md:mr-[10px] md:mb-[10px] h-full md:h-[calc(100%-10px)] rounded-[14px] border border-[#162B45] shadow-[0_2px_8px_rgba(0,0,0,0.2)]"
        )}
      >
        {/* 1. Header Bar with Clean Icon Controls (No Text Clutter, No Overlap) */}
        <div
          className={cn(
            "h-[48px] px-3 sm:px-4 border-b flex items-center justify-between flex-shrink-0 transition-colors",
            isDark ? "bg-[#0E1113] border-[#1A1F24]" : "bg-[#FFFFFF] border-[#E8E8E5]",
            "max-md:bg-black/30 max-md:border-b max-md:border-white/10 max-md:backdrop-blur-xl max-md:pt-[env(safe-area-inset-top,0px)] max-md:h-[calc(52px+env(safe-area-inset-top,0px))]"
          )}
        >
          {/* Left: Mobile Back Button + Sparkles Icon */}
          <div className="flex items-center gap-2 shrink-0">
            {/* Mobile Back Button */}
            <button
              onClick={onClose}
              className={cn(
                "md:hidden p-1.5 -ml-1 rounded-[8px] transition-colors cursor-pointer",
                isDark
                  ? "text-[#9CA3AF] hover:text-white hover:bg-[#1A1F24]"
                  : "text-[#6B7280] hover:text-[#0A0A0A] hover:bg-[#F0F0EE]",
                "max-md:text-white max-md:hover:bg-white/15"
              )}
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 stroke-[2]" />
            </button>

            {/* AI Sparkles Icon */}
            <div
              className={cn(
                "w-7 h-7 rounded-full flex items-center justify-center shrink-0",
                isDark ? "bg-[#1a73e8]/20 text-[#60a5fa]" : "bg-[#eff6ff] text-[#1a73e8]",
                "max-md:bg-cyan-500/25 max-md:text-cyan-300 max-md:shadow-[0_0_12px_rgba(0,229,255,0.4)]"
              )}
              title="Super Agent"
            >
              <Sparkles className="w-4 h-4 text-[#1a73e8] max-md:text-cyan-300 animate-ai-star" />
            </div>

            <div className="md:hidden flex items-center gap-1.5 pl-0.5">
              <span className="text-[13px] font-semibold text-white tracking-wide">Jarvis</span>
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#00e5ff]" />
            </div>
          </div>

          {/* Right: Icon-only Controls (New Chat, History, Fullscreen, Theme) */}
          <div className="flex items-center gap-1.5 shrink-0">
            {/* Quick Toggle to Active Item Drawer */}
            {activeDrawerInfo && (
              <button
                type="button"
                onClick={onClose}
                className={cn(
                  "hidden sm:inline-flex items-center gap-1 px-2 py-1 text-[11px] font-semibold border rounded-[7px] transition-colors cursor-pointer shrink-0",
                  isDark
                    ? "text-[#1a73e8] bg-[#161A1D] hover:bg-[#20262B] border-[#252B32]"
                    : "text-[#1557b0] bg-[#eff6ff] hover:bg-[#dbeafe] border-[#1a73e8]/30"
                )}
                title={`Back to ${activeDrawerInfo.kind} ${activeDrawerInfo.title}`}
              >
                <ArrowLeft className="w-3 h-3 text-[#1a73e8]" />
              </button>
            )}

            {/* New Chat Button */}
            <button
              type="button"
              onClick={superAgent.startNewChat}
              className={cn(
                "w-7 h-7 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer shrink-0",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#CBD5E1] hover:text-white"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#222222] hover:text-[#0A0A0A]"
              )}
              title="New Chat"
              aria-label="New Chat"
            >
              <Plus className="w-3.5 h-3.5 text-[#1a73e8]" />
            </button>

            {/* History Toggle Button */}
            <button
              type="button"
              onClick={superAgent.toggleHistoryOpen}
              className={cn(
                "w-7 h-7 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer shrink-0",
                superAgent.isHistoryOpen
                  ? isDark
                    ? "bg-[#1E2328] border-[#1a73e8]/50 text-white"
                    : "bg-[#eff6ff] border-[#1a73e8] text-[#1a73e8]"
                  : isDark
                    ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                    : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
              )}
              title="Conversation History"
              aria-label="Conversation History"
            >
              <History className="w-3.5 h-3.5" />
            </button>

            {/* Fullscreen / Restore Toggle Button */}
            <button
              type="button"
              onClick={() => setIsFullScreen((prev) => !prev)}
              className={cn(
                "hidden md:flex w-7 h-7 rounded-[7px] border items-center justify-center transition-colors cursor-pointer shrink-0",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF]"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#444444] hover:text-[#0A0A0A]"
              )}
              title={isFullScreen ? "Shrink to side panel" : "Full Screen"}
              aria-label={isFullScreen ? "Shrink to side panel" : "Full Screen"}
            >
              {isFullScreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
            </button>

            {/* Theme Toggle: Light / Dark Mode */}
            <button
              type="button"
              onClick={toggleTheme}
              className={cn(
                "w-7 h-7 rounded-[7px] border flex items-center justify-center transition-colors cursor-pointer shrink-0",
                isDark
                  ? "bg-[#14181B] hover:bg-[#1C2227] border-[#20262B] text-amber-300 hover:text-amber-200"
                  : "bg-[#F6F6F4] hover:bg-[#EBEBE8] border-[#E8E8E5] text-[#6B7280] hover:text-[#0A0A0A]"
              )}
              title={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
              aria-label={isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {isDark ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
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
                  <Plus className="w-3 h-3 text-[#1a73e8]" />
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
                                    ? "bg-[#161B20] text-white border-l-2 border-[#1a73e8]"
                                    : "bg-[#FFFFFF] text-[#0A0A0A] border-l-2 border-[#1a73e8] shadow-xs border-y border-r border-[#E8E8E5]"
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
                                  <Pin className={cn("w-3 h-3", conv.pinned ? "text-[#1a73e8] fill-[#1a73e8]" : isDark ? "text-[#64748B]" : "text-[#9CA3AF]")} />
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
                "flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-5 text-[13.5px] leading-relaxed min-w-0 w-full transition-colors",
                isDark ? "bg-[#0E1113]" : "bg-[#FFFFFF]",
                "max-md:bg-transparent max-md:p-3 max-md:pt-4"
              )}
            >
              <div className="max-w-[760px] mx-auto w-full space-y-4">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex flex-col gap-1 min-w-0",
                msg.sender === "user" ? "ml-auto items-end max-w-[85%] sm:max-w-[75%]" : "mr-auto items-start w-full max-w-full"
              )}
            >
              {msg.sender === "user" ? (
                /* User Chat Bubble: Modern pill capsule */
                <div
                  className={cn(
                    "px-4 py-2.5 rounded-[20px] text-[13.5px] leading-relaxed break-words [overflow-wrap:anywhere]",
                    isDark
                      ? "bg-[#20272E] border border-[#2E3742] text-[#F9FAFB]"
                      : "bg-[#F3F4F6] border border-[#E5E7EB] text-[#111827]",
                    "max-md:bg-cyan-500/20 max-md:border-cyan-400/35 max-md:text-white max-md:backdrop-blur-md max-md:shadow-[0_4px_16px_rgba(0,229,255,0.15)]"
                  )}
                >
                  <p className="whitespace-pre-line leading-relaxed">{msg.text}</p>
                </div>
              ) : (
                /* Assistant Message: Clean unboxed canvas (text flows freely, cards remain intact below) */
                <div className="w-full space-y-3 min-w-0 text-[13.5px] leading-relaxed">
                  <div
                    className={cn(
                      "whitespace-pre-line leading-relaxed break-words [overflow-wrap:anywhere] min-w-0 max-w-full",
                      isDark ? "text-[#E5E7EB]" : "text-[#111827]",
                      "max-md:text-white/95 max-md:drop-shadow-xs"
                    )}
                    dangerouslySetInnerHTML={{
                      __html: formatMarkdown(
                        msg.id === "initial-msg" ? t("agent.welcome_sub", msg.text) : msg.text,
                        isDark
                      ),
                    }}
                  />

                {/* The agent writes English; a Dutch dashboard offers the Dutch for it on demand. */}
                {language === "nl" && msg.id !== "initial-msg" && msg.text.trim() && (
                  <TranslationToggle text={msg.text} language="en" />
                )}

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
                            fact.isAlert ? "text-[#1a73e8]" : isDark ? "text-[#E2E8F0]" : "text-[#0A0A0A]"
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
                            isDark ? "bg-[#15181C] border-[#222830]" : "bg-[#FBFBFA] border-[#E8E8E5]",
                            "max-md:bg-black/55 max-md:border-white/15 max-md:backdrop-blur-xl max-md:shadow-[0_8px_32px_rgba(0,0,0,0.5)] max-md:rounded-[16px]"
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
                                className="text-[11px] font-medium text-[#1a73e8] hover:text-[#1557b0] flex items-center gap-1 cursor-pointer transition-colors"
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
                            className="font-medium text-[#1a73e8] hover:text-[#1557b0] flex items-center gap-1 cursor-pointer transition-colors"
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
                              <Calendar className="w-3 h-3 text-[#1a73e8]" />
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
                            <Clock className="w-3.5 h-3.5 text-[#1a73e8]" />
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
                              className="px-3 py-1.5 rounded-[7px] bg-[#1a73e8] hover:bg-[#1557b0] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
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
                              <FileText className="w-3 h-3 text-[#1a73e8]" />
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
                            className="text-[11px] font-medium text-[#1a73e8] hover:text-[#1557b0] flex items-center gap-1 cursor-pointer transition-colors"
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
                              <Sparkles className="w-3 h-3 text-[#1a73e8]" />
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
                              className="px-3 py-1.5 rounded-[7px] bg-[#1a73e8] hover:bg-[#1557b0] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
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
                            {t(pCard.badgeLabel || "NOTICE")}
                          </span>
                          <span className={cn("text-[10.5px] font-mono", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                            {pCard.unitLabel || "Action Required"}
                          </span>
                        </div>

                        <div className={cn("text-[13px] font-semibold", isDark ? "text-[#F9FAFB]" : "text-[#0A0A0A]")}>
                          {t(pCard.title || "Action Notice")}
                        </div>

                        <div className={cn(
                          "p-2.5 rounded-[8px] text-[12px] leading-relaxed font-sans break-words [overflow-wrap:anywhere] border",
                          isDark ? "bg-[#0E1113] border-amber-500/20 text-[#E2E8F0]" : "bg-[#FFFBEB] border-amber-200 text-[#78350F]"
                        )}>
                          {t(pCard.body || "")}
                        </div>

                        <div className={cn("pt-1 flex items-center justify-between gap-2 border-t", isDark ? "border-[#1E2328]" : "border-[#E8E8E5]")}>
                          <span className={cn("text-[10px] font-mono", isDark ? "text-[#64748B]" : "text-[#888888]")}>
                            {t("Status")}: {t(pCard.status || "pending")}
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
                                {t("Retry Draft")}
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => handleNavigate(pCard?.targetUrl || `/inbox?thread=case-${pCard?.caseId || ""}`)}
                              className="text-[11px] text-[#1a73e8] hover:underline flex items-center gap-1 cursor-pointer font-medium"
                            >
                              <span>{t("Open in Inbox")}</span>
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
                                      className="text-[11px] text-[#1a73e8] hover:underline cursor-pointer font-semibold"
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
                                    className="px-3 py-1.5 rounded-[7px] bg-[#1a73e8] hover:bg-[#1557b0] text-[#FFFFFF] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
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
              )}

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
                              ? "bg-[#1a73e8] hover:bg-[#1557b0] text-[#FFFFFF]"
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
                              <span>{t(act.label)}</span>
                              <CornerDownRight className="w-3 h-3" />
                            </>
                          )}
                        </button>
                      );
                    })}
                </div>
              )}

              {/* Pipeline debug is for developers: never shown to the owner unless NEXT_PUBLIC_SHOW_AGENT_DEBUG=1 */}
              {msg.debugInfo && process.env.NEXT_PUBLIC_SHOW_AGENT_DEBUG === "1" && (
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
            <div className="flex items-center gap-1.5 py-2 px-1 w-fit">
              <div className="w-2 h-2 rounded-full bg-[#1a73e8] animate-bounce" />
              <div className="w-2 h-2 rounded-full bg-[#1a73e8] animate-bounce [animation-delay:0.15s]" />
              <div className="w-2 h-2 rounded-full bg-[#1a73e8] animate-bounce [animation-delay:0.3s]" />
            </div>
          )}

          <div ref={messagesEndRef} />
              </div>
        </div>

        {/* 4. Floating Prompt Bar Footer (No hard border line, symmetrical spacing) */}
        <div
          className={cn(
            "px-4 sm:px-6 pt-1 flex-shrink-0 transition-colors bg-transparent",
            isFullScreen ? "pb-6 sm:pb-7" : "pb-3.5 sm:pb-4",
            "max-md:px-3 max-md:pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))]"
          )}
        >
          <div className="max-w-[760px] mx-auto w-full space-y-2.5">
            {/* Dynamic Next Step Suggestion Pills (Simple Plain Text, No Arrow) */}
            {suggestedChips.length > 0 && !isTyping && (
              <div className="flex items-center gap-2 overflow-x-auto pb-0.5 scrollbar-none no-scrollbar">
                {suggestedChips.slice(0, 3).map((chip: string, idx: number) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSendQuery(chip)}
                    className={cn(
                      "px-3.5 py-1 rounded-full border text-[12px] font-normal transition-all whitespace-nowrap cursor-pointer shrink-0 shadow-2xs hover:scale-[1.02] active:scale-[0.98]",
                      isDark
                        ? "bg-[#14181C] hover:bg-[#1E242B] border-[#222830] text-[#94a3b8] hover:text-white hover:border-[#1a73e8]/40"
                        : "bg-[#F8FAFD] hover:bg-[#eff6ff] border-[#DCE2EA] text-[#444746] hover:text-[#1a73e8] hover:border-[#1a73e8]/40",
                      "max-md:bg-black/45 max-md:border-white/20 max-md:text-white/85 max-md:backdrop-blur-lg max-md:hover:border-cyan-400"
                    )}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSendQuery(inputQuery);
              }}
              className={cn(
                "border-[1.5px] rounded-[20px] p-2.5 pb-2 flex flex-col gap-1.5 transition-all shadow-2xs",
                isDark
                  ? "bg-[#14181C] border-[#222830] focus-within:border-[#1a73e8] focus-within:bg-[#181D22]"
                  : "bg-[#f8fafd] border-[#dce2ea] focus-within:border-[#1a73e8] focus-within:bg-white",
                "max-md:bg-black/60 max-md:border-white/20 max-md:backdrop-blur-2xl max-md:shadow-[0_8px_32px_rgba(0,0,0,0.6)] max-md:rounded-[24px] max-md:focus-within:border-cyan-400 max-md:focus-within:bg-black/75"
              )}
            >
              <textarea
                ref={inputRef}
                rows={1}
                value={inputQuery}
                onChange={(e) => {
                  cancelAutoSend();
                  setInputQuery(e.target.value);
                }}
                onKeyDown={(e) => {
                  cancelAutoSend();
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSendQuery(inputQuery);
                  }
                }}
                placeholder={t("agent.ask_placeholder")}
                className={cn(
                  "w-full text-[13px] bg-transparent outline-none resize-none leading-relaxed",
                  isDark
                    ? "text-[#FFFFFF] placeholder:text-[#64748B]"
                    : "text-[#1f1f1f] placeholder:text-[#444746]",
                  "max-md:text-white max-md:placeholder:text-white/50"
                )}
              />

              <div className="flex items-center justify-between pt-0.5">
                {/* Voice Input Mic Button & Speech Language Switcher */}
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => toggleVoiceInput()}
                    className={cn(
                      "p-1.5 rounded-full transition-all cursor-pointer flex items-center justify-center shrink-0",
                      isListening
                        ? "bg-cyan-500 text-black shadow-[0_0_15px_rgba(0,229,255,0.7)] animate-pulse ring-2 ring-cyan-300"
                        : isDark
                        ? "text-slate-400 hover:text-white hover:bg-white/10"
                        : "text-[#5f6368] hover:text-[#1a73e8] hover:bg-slate-100"
                    )}
                    title={isListening ? "Listening... click to stop" : `Voice input (${speechLang === "nl" ? "Dutch" : "English"})`}
                    aria-label="Voice input"
                  >
                    {isListening ? (
                      <MicOff className="w-4 h-4 stroke-[2.5]" />
                    ) : (
                      <Mic className="w-4 h-4 stroke-[2]" />
                    )}
                  </button>

                  {/* Speech Language Switcher */}
                  <button
                    type="button"
                    onClick={handleToggleLang}
                    className={cn(
                      "text-[10px] font-bold px-2 py-0.5 rounded-full border transition-all cursor-pointer flex items-center gap-1 select-none",
                      speechLang === "nl"
                        ? "bg-amber-500/15 text-amber-400 border-amber-500/30 hover:bg-amber-500/25"
                        : "bg-blue-500/15 text-blue-400 border-blue-500/30 hover:bg-blue-500/25"
                    )}
                    title={speechLang === "nl" ? "Voice language: Nederlands (click to switch to English)" : "Voice language: English (click to switch to Nederlands)"}
                  >
                    <span>{speechLang === "nl" ? "🇳🇱 NL" : "🇬🇧 EN"}</span>
                  </button>

                  {isListening && (
                    <span className="text-[11px] text-cyan-400 font-medium animate-pulse flex items-center gap-1 pl-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping inline-block" />
                      {isPausingToAutoSend
                        ? "⚡ Sending..."
                        : speechLang === "nl"
                        ? "Luisteren (Dutch)..."
                        : "Listening (English)..."}
                    </span>
                  )}
                  {voiceError && !isListening && (
                    <span className="text-[11px] text-amber-500 font-medium pl-1">{voiceError}</span>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={!inputQuery.trim() || isTyping}
                  className={cn(
                    "w-7 h-7 rounded-full flex items-center justify-center transition-all cursor-pointer shrink-0",
                    inputQuery.trim()
                      ? "bg-[#1a73e8] max-md:bg-gradient-to-r max-md:from-cyan-400 max-md:to-blue-600 max-md:text-black hover:bg-[#1557b0] text-white shadow-[0_2px_6px_rgba(26,115,232,0.3)] max-md:shadow-[0_0_12px_rgba(0,229,255,0.4)] hover:scale-105 active:scale-95"
                      : isDark
                      ? "bg-[#1c2227] max-md:bg-white/10 text-[#64748b] max-md:text-white/30 cursor-not-allowed opacity-60"
                      : "bg-[#e8eaed] max-md:bg-white/10 text-[#5f6368] max-md:text-white/30 cursor-not-allowed opacity-70"
                  )}
                  title="Send query"
                >
                  <ArrowUp className="w-3.5 h-3.5 stroke-[2.5]" />
                </button>
              </div>
            </form>
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
