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
} from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { askAgent, approveInboxDraft } from "@/lib/api";

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
  const [sendingCardId, setSendingCardId] = useState<string | null>(null);
  const [approvingCalendarId, setApprovingCalendarId] = useState<string | null>(null);
  const [approvedCalendarIds, setApprovedCalendarIds] = useState<Set<string>>(new Set());
  const [sentCardIds, setSentCardIds] = useState<Set<string>>(new Set());
  const [sendErrorCardIds, setSendErrorCardIds] = useState<Set<string>>(new Set());

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

  // Context-aware suggested chips per section
  const suggestedChips = React.useMemo(() => {
    if (currentPageName.toLowerCase().includes("inbox")) {
      return [
        "Summarize unread tenant emails",
        "Explain emergency leak in Pieter Floriszstraat",
        "Draft technician work order",
        "Who needs a follow-up today?",
      ];
    }
    if (currentPageName.toLowerCase().includes("money")) {
      return [
        "Why is invoice 26.13.00024 still open?",
        "Which payments need matching?",
        "Who is 30+ days behind on rent?",
        "Show total unpaid rent across 110 units",
      ];
    }
    if (currentPageName.toLowerCase().includes("maintenance")) {
      return [
        "Which tickets have gone quiet?",
        "Show electrician dispatch status for #005",
        "What quotes exceed the €250 limit?",
        "List pending contractor invoices",
      ];
    }
    // Default: Today page
    return [
      "What should I do first?",
      "Explain this item",
      "Who is behind on rent?",
      "Show the energy label",
    ];
  }, [currentPageName]);

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
        recentHistory
      );

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
        actions: parsedActions.length > 0 ? parsedActions : undefined,
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

  const handleApproveDraft = async (cardId: string, actionId?: string | null, caseId?: string | null) => {
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
      const res = await approveInboxDraft(cleanId, "d1");
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
          "bg-[#0E1113] text-[#F3F4F6] shadow-2xl flex flex-col justify-between font-sans border-[#22282E]",
          isFullScreen
            ? "fixed inset-2 md:inset-6 z-50 rounded-[18px] border overflow-hidden transition-all duration-200 animate-in zoom-in-95"
            : panelMode === "center"
            ? "fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[95vw] sm:w-[85vw] md:w-[40vw] md:min-w-[500px] md:max-w-[720px] h-[82vh] max-h-[850px] rounded-[18px] border overflow-hidden transition-all duration-200 animate-in zoom-in-95"
            : "fixed inset-0 z-50 md:sticky md:top-0 md:right-0 md:z-30 w-full md:w-[32vw] md:min-w-[360px] md:max-w-[520px] h-dvh md:h-screen md:border-l flex-shrink-0 overflow-hidden transition-all duration-200 animate-in slide-in-from-right-4"
        )}
      >
        {/* 1. Header Bar with Integrated Context Tag (No extra box bar needed) */}
        <div className="h-14 px-4 sm:px-5 border-b border-[#1A1F24] flex items-center justify-between flex-shrink-0 bg-[#0E1113]">
          <div className="flex items-center gap-2.5 min-w-0">
            {/* Mobile Back Button */}
            <button
              onClick={onClose}
              className="md:hidden p-1.5 -ml-1 rounded-[8px] text-[#9CA3AF] hover:text-white hover:bg-[#1A1F24] transition-colors cursor-pointer"
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 stroke-[2]" />
            </button>

            {/* AI Agent Icon */}
            <div className="w-7 h-7 rounded-[8px] bg-[#161A1D] border border-[#252B32] flex items-center justify-center text-emerald-400 shadow-xs shrink-0">
              <Sparkles className="w-3.5 h-3.5" />
            </div>

            {/* Title & Page Context */}
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-heading font-semibold text-[14px] text-[#F9FAFB] tracking-tight shrink-0">
                Super Agent
              </span>
              <span className="text-[10px] font-mono uppercase bg-[#161A1D] text-[#94A3B8] border border-[#252B32] px-1.5 py-0.5 rounded-[5px] shrink-0">
                Concierge
              </span>
              {/* Context Tag integrated into header (removes separate box) */}
              <div className="hidden sm:flex items-center gap-1.5 px-2 py-0.5 rounded-[5px] bg-[#14181B] border border-[#1E2328] text-[11px] text-[#94A3B8] min-w-0 truncate">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                <span className="truncate">{currentPageName} · {selectedContext}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {/* Quick Toggle to Active Item Drawer (Unified Right Rail) */}
            {activeDrawerInfo && (
              <button
                type="button"
                onClick={onClose}
                className="hidden sm:inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-[#F25C05] bg-[#161A1D] hover:bg-[#20262B] border border-[#252B32] rounded-[7px] transition-colors cursor-pointer shrink-0"
                title={`Switch back to ${activeDrawerInfo.kind} ${activeDrawerInfo.title}`}
              >
                <ArrowLeft className="w-3 h-3 text-[#F25C05]" />
                <span>Back to {activeDrawerInfo.kind} {activeDrawerInfo.title}</span>
              </button>
            )}

            {/* Mode Switcher: Center (40%) <-> Dock (30%) */}
            <button
              onClick={togglePanelMode}
              className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-[7px] bg-[#14181B] hover:bg-[#1C2227] border border-[#20262B] text-[11px] text-[#94A3B8] hover:text-[#FFFFFF] transition-colors cursor-pointer"
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
              className="hidden md:flex w-8 h-8 rounded-[7px] bg-[#14181B] hover:bg-[#1C2227] border border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF] items-center justify-center transition-colors cursor-pointer"
              title={isFullScreen ? "Restore Window" : "Expand to Full Screen"}
            >
              {isFullScreen ? (
                <Minimize2 className="w-3.5 h-3.5" />
              ) : (
                <Maximize2 className="w-3.5 h-3.5" />
              )}
            </button>

            {/* Close Button */}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-[7px] bg-[#14181B] hover:bg-[#1C2227] border border-[#20262B] text-[#94A3B8] hover:text-[#FFFFFF] flex items-center justify-center transition-colors cursor-pointer"
              title="Close (Esc)"
            >
              <X className="w-4 h-4 stroke-[2]" />
            </button>
          </div>
        </div>

        {/* 2. Scrollable Message Thread */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-5 space-y-4 text-[13.5px] leading-relaxed min-w-0 w-full">
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
                    ? "bg-[#1C2329] border border-[#28323B] text-[#F3F4F6] rounded-tr-none"
                    : "bg-[#121518] border border-[#1E2328] text-[#E2E8F0] rounded-tl-none shadow-sm w-full"
                )}
              >
                <div
                  className="whitespace-pre-line leading-relaxed break-words [overflow-wrap:anywhere] min-w-0 max-w-full"
                  dangerouslySetInnerHTML={{
                    __html: formatMarkdown(msg.text),
                  }}
                />

                {/* Read citation: subtle inline text */}
                {msg.readSource && (
                  <div className="mt-2.5 pt-2 border-t border-[#1E2328] text-[11px] text-[#64748B] flex items-center gap-1.5 font-mono">
                    <span className="text-[#94A3B8]">Read:</span>
                    <span className="truncate">{msg.readSource}</span>
                  </div>
                )}

                {/* Facts: Minimal 2-column key/value list without heavy nested boxes */}
                {msg.facts && msg.facts.length > 0 && (
                  <div className="mt-3 pt-2.5 border-t border-[#1E2328] grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11.5px]">
                    {msg.facts.map((fact, idx) => (
                      <div key={idx} className="flex flex-col">
                        <span className="text-[10px] uppercase font-mono text-[#64748B] tracking-wider mb-0.5">
                          {fact.label}
                        </span>
                        <span className={cn("font-medium truncate", fact.isAlert ? "text-[#F25C05]" : "text-[#E2E8F0]")}>
                          {fact.value}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Live Step Checklist: Filter out internal technical/database jargon */}
                {msg.steps &&
                  msg.steps.filter((st) => !/embedding|postgres|chunks|dim|rag|memory_items|document_chunks/i.test(st)).length > 0 && (
                  <div className="mt-2.5 space-y-1.5 text-[12px] text-[#94A3B8]">
                    {msg.steps
                      .filter((st) => !/embedding|postgres|chunks|dim|rag|memory_items|document_chunks/i.test(st))
                      .map((st, sIdx) => (
                        <div key={sIdx} className="flex items-center gap-2">
                          <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                          <span className="leading-tight">{st}</span>
                        </div>
                      ))}
                  </div>
                )}

                {/* Mini Preview Workspace Card (Single clean container, color reserved for important items) */}
                {msg.previewCard && (
                  <div className="mt-3 rounded-[10px] bg-[#15181C] border border-[#222830] p-3.5 space-y-2.5 shadow-sm animate-in fade-in-50 duration-150 min-w-0 max-w-full overflow-hidden">
                    {/* 1. Case Snapshot Card */}
                    {msg.previewCard.type === "case_summary" ? (
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B]">
                              {msg.previewCard.badgeLabel || "TICKET"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {msg.previewCard.unitLabel || "Portfolio"}
                            </span>
                          </div>
                          {msg.previewCard.status && (
                            <span className="text-[10.5px] font-mono text-[#94A3B8] capitalize">
                              {msg.previewCard.status}
                            </span>
                          )}
                        </div>
                        <div className="text-[12.5px] text-[#E2E8F0] leading-relaxed font-sans break-words [overflow-wrap:anywhere]">
                          {msg.previewCard.body || msg.previewCard.title}
                        </div>
                        {msg.previewCard.contractor && (
                          <div className="text-[11px] text-[#64748B] flex items-center justify-between pt-1 border-t border-[#1E2328]">
                            <span>Contractor: <strong className="text-[#CBD5E1]">{msg.previewCard.contractor}</strong></span>
                            {msg.previewCard.dueDate && <span className="font-mono text-[10.5px] text-[#94A3B8]">{msg.previewCard.dueDate}</span>}
                          </div>
                        )}
                        <div className="pt-1.5 flex items-center justify-end">
                          <button
                            type="button"
                            onClick={() => {
                              if (msg.previewCard?.targetUrl?.startsWith("http")) {
                                window.open(msg.previewCard.targetUrl, "_blank", "noopener,noreferrer");
                              } else {
                                handleNavigate(msg.previewCard?.targetUrl || (msg.previewCard?.caseId ? `/maintenance?ticket=${msg.previewCard.caseId}` : "/maintenance"));
                              }
                            }}
                            className="text-[11px] font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                          >
                            <span>
                              {msg.previewCard.badgeLabel === "GOOGLE DRIVE"
                                ? "Open in Google Drive"
                                : "Open in Maintenance"}
                            </span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    ) : msg.previewCard.type === "financial_item" ? (
                      /* 2. Financial Arrears / Ledger Card (Amount is the important highlight) */
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B]">
                            {msg.previewCard.badgeLabel || "ARREARS"}
                          </span>
                          {/* Amount is highlighted in red because it's an overdue financial figure */}
                          <span className="font-mono text-[14px] font-bold text-rose-400">
                            {msg.previewCard.amount}
                          </span>
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB] break-words">
                          {msg.previewCard.title}
                        </div>
                        <div className="text-[12px] text-[#94A3B8] leading-relaxed break-words [overflow-wrap:anywhere]">
                          {msg.previewCard.subtitle || msg.previewCard.body}
                        </div>
                        <div className="pt-2 flex items-center justify-between border-t border-[#1E2328] text-[11px]">
                          <span className="text-[#64748B] font-mono text-[10.5px]">
                            {msg.previewCard.dueDate ? `Due: ${msg.previewCard.dueDate}` : msg.previewCard.unitLabel}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleNavigate(msg.previewCard?.targetUrl || "/money")}
                            className="font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                          >
                            <span>Open in Money</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    ) : msg.previewCard.type === "calendar_item" ? (
                      /* Calendar Appointment Proposal Card */
                      <div className="space-y-2.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B] flex items-center gap-1">
                              <Calendar className="w-3 h-3 text-[#F25C05]" />
                              {msg.previewCard.badgeLabel || "GOOGLE CALENDAR"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {msg.previewCard.unitLabel || "Portfolio Visit"}
                            </span>
                          </div>
                          <span
                            className={cn(
                              "text-[10.5px] font-mono capitalize",
                              approvedCalendarIds.has(msg.id) || msg.previewCard.status === "confirmed"
                                ? "text-emerald-400 font-semibold"
                                : "text-amber-400"
                            )}
                          >
                            {approvedCalendarIds.has(msg.id) || msg.previewCard.status === "confirmed" ? "Confirmed" : "Proposed"}
                          </span>
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB]">
                          {msg.previewCard.title}
                        </div>
                        <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] space-y-1.5 text-[12px] text-[#CBD5E1]">
                          <div className="flex items-center gap-1.5 text-[#E2E8F0]">
                            <Clock className="w-3.5 h-3.5 text-[#F25C05]" />
                            <span className="font-medium">{msg.previewCard.dueDate || msg.previewCard.subtitle}</span>
                          </div>
                          {msg.previewCard.contractor && (
                            <div className="text-[#94A3B8] text-[11.5px]">
                              Contractor: <span className="text-[#F1F5F9]">{msg.previewCard.contractor}</span>
                            </div>
                          )}
                          {msg.previewCard.body && (
                            <div className="text-[11.5px] text-[#94A3B8] whitespace-pre-line border-t border-[#1E2328] pt-1 mt-1">
                              {msg.previewCard.body}
                            </div>
                          )}
                        </div>
                        <div className="pt-1.5 flex items-center justify-between border-t border-[#1E2328]">
                          <span className="text-[10.5px] font-mono text-[#64748B]">
                            {approvedCalendarIds.has(msg.id) || msg.previewCard.status === "confirmed"
                              ? "Synced to Google Calendar"
                              : "Requires 1-click confirmation"}
                          </span>
                          {approvedCalendarIds.has(msg.id) || msg.previewCard.status === "confirmed" ? (
                            <div className="flex items-center gap-1.5 text-emerald-400 text-[11.5px] font-semibold">
                              <CheckCircle2 className="w-4 h-4" />
                              <span>Added to Google Calendar</span>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => handleApproveCalendar(msg.id, msg.previewCard?.actionId)}
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
                    ) : msg.previewCard.type === "document_item" ? (
                      /* 3. Document / Google Drive Verified Match Card */
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-[11px]">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B] flex items-center gap-1">
                              <FileText className="w-3 h-3 text-[#F25C05]" />
                              {msg.previewCard.badgeLabel || "GOOGLE DRIVE"}
                            </span>
                            <span className="text-[#F3F4F6] font-medium truncate max-w-[200px]">
                              {msg.previewCard.unitLabel || "Portfolio Document"}
                            </span>
                          </div>
                          {msg.previewCard.status && (
                            <span className="text-[10.5px] font-mono text-emerald-400">
                              {msg.previewCard.status}
                            </span>
                          )}
                        </div>
                        <div className="text-[13px] font-semibold text-[#F9FAFB]">
                          {msg.previewCard.title}
                        </div>
                        {msg.previewCard.body && (
                          <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] text-[12px] text-[#CBD5E1] font-sans leading-relaxed break-words [overflow-wrap:anywhere]">
                            {msg.previewCard.body}
                          </div>
                        )}
                        <div className="pt-1.5 flex items-center justify-end">
                          <button
                            type="button"
                            onClick={() => {
                              if (msg.previewCard?.targetUrl?.startsWith("http")) {
                                window.open(msg.previewCard.targetUrl, "_blank", "noopener,noreferrer");
                              } else {
                                handleNavigate(msg.previewCard?.targetUrl || "/documents");
                              }
                            }}
                            className="text-[11px] font-medium text-[#F25C05] hover:text-[#d94f00] flex items-center gap-1 cursor-pointer transition-colors"
                          >
                            <span>Open in Google Drive</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* 4. Default: Message Draft Card (WhatsApp / Gmail) */
                      <div className="space-y-2.5">
                        <div className="flex items-center justify-between text-[11px] text-[#94A3B8]">
                          <span className="font-mono text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#1F252C] text-[#CBD5E1] border border-[#29323B]">
                            Draft · {msg.previewCard.channel || "whatsapp"}
                          </span>
                          <span className="font-mono text-[10.5px] text-[#64748B]">
                            {msg.previewCard.recipient}
                          </span>
                        </div>

                        <div className="p-2.5 rounded-[8px] bg-[#0E1113] border border-[#1E2328] text-[12px] text-[#E2E8F0] italic whitespace-pre-line leading-relaxed font-sans break-words [overflow-wrap:anywhere]">
                          "{msg.previewCard.body && msg.previewCard.body !== "--" ? msg.previewCard.body : "Beste bewoner,\n\nDank voor uw melding. We hebben uw bericht ontvangen en zijn direct bezig met de opvolging.\n\nMet vriendelijke groet,\nHarjot — EstateOS"}"
                        </div>

                        <div className="pt-1 flex items-center justify-between gap-2">
                          <div>
                            {sentCardIds.has(msg.id) ? (
                              <div className="flex items-center gap-1.5 text-emerald-400 text-[11.5px] font-medium py-1">
                                <Check className="w-4 h-4 stroke-[2.5]" />
                                <span>Dispatched to {msg.previewCard.channel || "WhatsApp"}</span>
                              </div>
                            ) : sendErrorCardIds.has(msg.id) ? (
                              <div className="flex items-center gap-2">
                                <span className="text-rose-400 text-[11px]">Failed to dispatch draft.</span>
                                <button
                                  type="button"
                                  onClick={() => handleApproveDraft(msg.id, msg.previewCard?.actionId, msg.previewCard?.caseId)}
                                  className="text-[11px] text-[#F25C05] hover:underline cursor-pointer font-semibold"
                                >
                                  Retry
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={() => handleApproveDraft(msg.id, msg.previewCard?.actionId, msg.previewCard?.caseId)}
                                disabled={sendingCardId === msg.id}
                                className="px-3 py-1.5 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
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
                          </div>

                          <button
                            type="button"
                            onClick={() => {
                              const draftText = msg.previewCard?.body ? encodeURIComponent(msg.previewCard.body) : "";
                              const baseTarget = msg.previewCard?.targetUrl || `/inbox?thread=case-${msg.previewCard?.caseId || ""}`;
                              const urlWithDraft = draftText && !baseTarget.includes("draft=")
                                ? `${baseTarget}${baseTarget.includes("?") ? "&" : "?"}draft=${draftText}`
                                : baseTarget;
                              handleNavigate(urlWithDraft);
                            }}
                            className="text-[11px] text-[#888888] hover:text-[#FFFFFF] flex items-center gap-1 transition-colors cursor-pointer"
                          >
                            <span>Open in Inbox</span>
                            <ExternalLink className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

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
                    .map((act, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => handleActionClick(act)}
                        className={cn(
                          "px-3 py-1.5 rounded-[8px] text-[12px] font-semibold transition-colors flex items-center gap-1.5 cursor-pointer shadow-xs",
                          act.isPrimary
                            ? "bg-[#F25C05] hover:bg-[#d94f00] text-[#0A0A0A]"
                            : "bg-[#181818] hover:bg-[#222222] border border-[#262626] text-[#FFFFFF]"
                        )}
                      >
                        <span>{act.label}</span>
                        <CornerDownRight className="w-3 h-3" />
                      </button>
                    ))}
                </div>
              )}

              <span className="text-[10px] font-mono text-[#666666] px-1">
                {msg.timestamp}
              </span>
            </div>
          ))}

          {/* Animated 3-dot Typing Indicator */}
          {isTyping && (
            <div className="flex items-center gap-1.5 p-3 rounded-[12px] bg-[#14181B] border border-[#20262B] w-fit text-[#888888]">
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.15s]" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.3s]" />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 3. Suggested Chips: Streamlined minimal pills, no heavy container */}
        <div className="px-4 sm:px-5 py-2 border-t border-[#1A1F24] bg-[#0E1113] flex-shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {suggestedChips.slice(0, 3).map((chip, idx) => (
              <button
                key={idx}
                onClick={() => handleSendQuery(chip)}
                className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#14181B] hover:bg-[#1C2227] border border-[#20262B] hover:border-[#334155] text-[11px] text-[#94A3B8] hover:text-[#FFFFFF] transition-colors cursor-pointer"
              >
                <span>{chip}</span>
                <ArrowUpRight className="w-3 h-3 text-[#64748B]" />
              </button>
            ))}
          </div>
        </div>

        {/* 4. Input Field Row: Sleek and flat */}
        <div className="p-3.5 sm:p-4 border-t border-[#1A1F24] bg-[#0B0D0E] flex-shrink-0">
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
                className="w-full h-10 pl-3.5 pr-11 rounded-[10px] bg-[#14181C] border border-[#222830] text-[13px] text-[#FFFFFF] placeholder:text-[#64748B] focus:outline-none focus:border-[#4B5563] transition-colors"
              />
              <button
                type="submit"
                disabled={!inputQuery.trim() || isTyping}
                className="absolute right-1.5 w-7 h-7 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] disabled:opacity-30 text-[#0A0A0A] flex items-center justify-center transition-colors cursor-pointer"
                title="Send query"
              >
                <Send className="w-3.5 h-3.5 stroke-[2.4]" />
              </button>
            </form>

            <p className="text-[10px] text-[#475569] text-center leading-tight">
              Autonomous planning with explicit confirmation before dispatch.
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}



function formatMarkdown(text: string): string {
  return text
    // Markdown links: [Label](url) -> clean clickable anchor tag with break-all
    .replace(
      /\[(.*?)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer" class="text-[#F25C05] hover:text-[#d94f00] underline font-medium inline-flex items-center gap-1 break-all">$1 ↗</a>'
    )
    // Inline backticks: `code`
    .replace(
      /`([^`]+)`/g,
      '<code class="px-1.5 py-0.5 rounded bg-[#181D22] text-[#E2E8F0] font-mono text-[12px] break-all border border-[#262F38]">$1</code>'
    )
    // Bold: **text**
    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-[#FFFFFF] font-semibold">$1</strong>')
    // Italics: *text*
    .replace(/\*(.*?)\*/g, '<em class="text-[#CCCCCC]">$1</em>')
    // Bullet list: • or -
    .replace(
      /^([•\-]) (.*?)$/gm,
      '<div class="flex items-start gap-2 my-1"><span class="text-[#F25C05] font-bold shrink-0">•</span><span class="break-words min-w-0">$2</span></div>'
    );
}
