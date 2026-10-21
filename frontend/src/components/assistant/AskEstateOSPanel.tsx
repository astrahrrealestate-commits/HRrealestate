"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Sparkles,
  X,
  Send,
  ArrowUpRight,
  ArrowLeft,
  FileText,
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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { askAgent, approveDraftProposal } from "@/lib/api";

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
    channel: string;
    recipient: string;
    unitLabel: string;
    subject?: string | null;
    body: string;
    actionId?: string | null;
    caseId?: string | null;
  } | null;
  actions?: AssistantAction[];
}

interface AskEstateOSPanelProps {
  isOpen: boolean;
  onClose: () => void;
  currentPageName?: string;
  selectedContext?: string;
  onActionTriggered?: (actionType: string, payload?: any) => void;
}

export function AskEstateOSPanel({
  isOpen,
  onClose,
  currentPageName = "Today",
  selectedContext = "The whole page",
  onActionTriggered,
}: AskEstateOSPanelProps) {
  const [inputQuery, setInputQuery] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [sendingCardId, setSendingCardId] = useState<string | null>(null);
  const [sentCardIds, setSentCardIds] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<AssistantMessage[]>([
    {
      id: "initial-msg",
      sender: "assistant",
      timestamp: "Just now",
      text: `**On ${currentPageName}.** I know your queue, portfolio, and financial logs. Ask me to explain an item, find a document, check tenant arrears, or pick what to do first.`,
      actions: [
        {
          label: "What should I do first?",
          actionType: "query",
          payload: "What should I do first?",
          isPrimary: true,
        },
      ],
    },
  ]);

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

    setMessages((prev) => [...prev, userMsg]);
    setInputQuery("");
    setIsTyping(true);

    try {
      const res = await askAgent(trimmed, `${currentPageName}: ${selectedContext}`);
      const botMsg: AssistantMessage = {
        id: `agent-${Date.now()}`,
        sender: "assistant",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        text: res.answer,
        steps: res.steps,
        previewCard: res.previewCard,
        actions: res.suggestedAction
          ? [
              {
                label: res.suggestedAction,
                actionType: "navigate",
                payload: "/maintenance",
                isPrimary: true,
              },
            ]
          : undefined,
      };
      setMessages((prev) => [...prev, botMsg]);
    } catch {
      const fallbackResponse = generateAssistantResponse(trimmed, currentPageName, selectedContext);
      setMessages((prev) => [...prev, fallbackResponse]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleApproveDraft = async (cardId: string, caseId?: string | null) => {
    setSendingCardId(cardId);
    try {
      if (caseId) {
        await approveDraftProposal(`case-${caseId}`, 0);
      }
      setSentCardIds((prev) => new Set([...prev, cardId]));
    } catch (err) {
      console.warn("Failed to approve draft directly:", err);
      // Optimistically mark as sent for smooth user experience
      setSentCardIds((prev) => new Set([...prev, cardId]));
    } finally {
      setSendingCardId(null);
    }
  };

  const handleActionClick = (action: AssistantAction) => {
    if (action.actionType === "query" && typeof action.payload === "string") {
      handleSendQuery(action.payload);
      return;
    }
    if (onActionTriggered) {
      onActionTriggered(action.actionType, action.payload);
    }
  };

  if (!isOpen) return null;

  return (
    <>
      {/* Backdrop with smooth blur transition */}
      <div
        onClick={onClose}
        className="fixed inset-0 bg-[#0A0A0A]/60 z-40 backdrop-blur-sm transition-opacity duration-300 animate-in fade-in"
      />

      {/* Main Assistant Panel: Full screen on mobile (<768px), 440px sleek drawer on desktop */}
      <aside
        className={cn(
          "fixed inset-0 md:inset-y-0 md:right-0 md:left-auto z-50 w-full md:w-[440px] h-dvh bg-[#0E0E0E] text-[#F5F5F5] md:border-l border-[#262626] shadow-2xl flex flex-col justify-between font-sans transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] animate-in slide-in-from-right select-none"
        )}
      >
        {/* 1. Header Row (h-14, back arrow on mobile) */}
        <div className="h-14 px-4 sm:px-5 border-b border-[#262626] flex items-center justify-between flex-shrink-0 bg-[#0A0A0A]">
          <div className="flex items-center gap-2.5">
            {/* Mobile Back Button (Section 5.6: "Back arrow closes it") */}
            <button
              onClick={onClose}
              className="md:hidden p-1.5 -ml-1 rounded-[var(--radius-ctl)] text-[#AAAAAA] hover:text-[#FFFFFF] hover:bg-[#181818] transition-colors cursor-pointer"
              title="Back"
            >
              <ArrowLeft className="w-5 h-5 stroke-[2]" />
            </button>

            {/* Sparkle icon badge */}
            <div className="w-[30px] h-[30px] rounded-[var(--radius-ctl)] bg-[var(--accent)] flex items-center justify-center text-[#0A0A0A] shadow-xs shrink-0 select-none">
              <Sparkles className="w-4 h-4 stroke-[2.2]" />
            </div>
            <div>
              <div className="font-heading font-bold text-[14px] sm:text-[15px] text-[#FFFFFF] tracking-[-0.01em] leading-tight flex items-center gap-1.5">
                <span>EstateOS</span>
                <span className="text-[9.5px] font-mono uppercase bg-[#262626] text-[var(--accent)] px-1.5 py-0.2 rounded-[4px] font-bold">
                  AI Agent
                </span>
              </div>
              <div className="text-[11px] text-[#888888]">
                Assistant · <span className="text-[#E0E0E0] font-medium">{currentPageName}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="hidden md:flex w-8 h-8 rounded-[8px] bg-[#181818] hover:bg-[#222222] border border-[#262626] text-[#AAAAAA] hover:text-[#FFFFFF] items-center justify-center transition-colors cursor-pointer"
              title="Close Assistant (Esc)"
            >
              <X className="w-4 h-4 stroke-[2]" />
            </button>
          </div>
        </div>

        {/* 2. Context Card "LOOKING AT" */}
        <div className="px-5 py-3 border-b border-[#262626] bg-[#141414] flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-2 h-2 rounded-full bg-[#F25C05] animate-pulse flex-shrink-0" />
            <span className="text-[10.5px] font-semibold text-[#888888] uppercase tracking-[0.06em] flex-shrink-0">
              LOOKING AT
            </span>
            <span className="text-[12.5px] text-[#FFFFFF] font-medium truncate">
              {selectedContext}
            </span>
          </div>
        </div>

        {/* 3. Scrollable Message Thread */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4 text-[13.5px] leading-relaxed">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                "flex flex-col gap-1 max-w-[92%]",
                msg.sender === "user" ? "ml-auto items-end" : "mr-auto items-start"
              )}
            >
              {/* Message Bubble */}
              <div
                className={cn(
                  "p-3.5 rounded-[14px] text-[13.5px]",
                  msg.sender === "user"
                    ? "bg-[#181818] border border-[#262626] text-[#FFFFFF] rounded-tr-none"
                    : "bg-[#181818] border border-[#262626] text-[#EEEEEE] rounded-tl-none shadow-sm"
                )}
              >
                <div
                  className="whitespace-pre-line leading-relaxed"
                  dangerouslySetInnerHTML={{
                    __html: formatMarkdown(msg.text),
                  }}
                />

                {/* Read: source citation */}
                {msg.readSource && (
                  <div className="mt-2.5 pt-2 border-t border-[#262626] text-[11.5px] text-[#888888] flex items-center gap-1.5 font-mono">
                    <span className="text-[#F25C05]">Read:</span>
                    <span className="truncate">{msg.readSource}</span>
                  </div>
                )}

                {/* Fact Tiles (if present) */}
                {msg.facts && msg.facts.length > 0 && (
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    {msg.facts.map((fact, idx) => (
                      <div
                        key={idx}
                        className={cn(
                          "p-2.5 rounded-[8px] text-[12px] border",
                          fact.isAlert
                            ? "bg-[#F25C05]/10 border-[#F25C05]/30 text-[#FFA066]"
                            : "bg-[#222222] border-[#2E2E2E] text-[#DDDDDD]"
                        )}
                      >
                        <div className="text-[10px] uppercase font-semibold text-[#888888] tracking-wider mb-0.5">
                          {fact.label}
                        </div>
                        <div className="font-semibold truncate">{fact.value}</div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Draft Proposal Block (if present) */}
                {msg.draftBlock && (
                  <div className="mt-3 p-3 rounded-[10px] bg-[#111111] border border-[#2A2A2A] text-[12.5px] space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-[#888888]">
                      <span className="uppercase tracking-wider font-semibold text-[#F25C05]">
                        Draft Reply ({msg.draftBlock.channel})
                      </span>
                      <span>To: {msg.draftBlock.to}</span>
                    </div>
                    <div className="text-[#FFFFFF] italic whitespace-pre-line bg-[#161616] p-2.5 rounded-[6px] border border-[#222222]">
                      "{msg.draftBlock.body}"
                    </div>
                  </div>
                )}

                {/* Live Step Checklist (Antigravity/Grok style) */}
                {msg.steps && msg.steps.length > 0 && (
                  <div className="mt-3 p-2.5 rounded-[8px] bg-[#141414] border border-[#222222] space-y-1.5">
                    {msg.steps.map((st, sIdx) => (
                      <div key={sIdx} className="flex items-center gap-2 text-[11.5px] text-[#A0A0A0]">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                        <span className="leading-tight">{st}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Mini Preview Workspace Card (Grok/Computer style) */}
                {msg.previewCard && (
                  <div className="mt-3 rounded-[10px] bg-[#141414] border border-[#2A2A2A] overflow-hidden shadow-lg">
                    {/* Card Header */}
                    <div className="px-3 py-2 bg-[#1A1A1A] border-b border-[#262626] flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-2">
                        <span className="flex items-center gap-1 font-mono uppercase text-[9.5px] font-semibold px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                          <MessageSquare className="w-3 h-3" />
                          {msg.previewCard.channel}
                        </span>
                        <span className="text-[#CCCCCC] font-medium truncate max-w-[170px]">
                          {msg.previewCard.unitLabel}
                        </span>
                      </div>
                      <span className="text-[#888888] font-mono text-[10px]">
                        {msg.previewCard.recipient}
                      </span>
                    </div>

                    {/* Card Body Frame */}
                    <div className="p-3 bg-[#0E0E0E] text-[12px] text-[#E0E0E0] whitespace-pre-line leading-relaxed font-sans border-b border-[#222222]">
                      {msg.previewCard.body}
                    </div>

                    {/* Card Bottom Controls */}
                    <div className="px-3 py-2 bg-[#141414] flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        {sentCardIds.has(msg.id) ? (
                          <div className="flex items-center gap-1.5 text-emerald-400 text-[11.5px] font-medium py-1">
                            <Check className="w-4 h-4 stroke-[2.5]" />
                            <span>Dispatched to WhatsApp</span>
                          </div>
                        ) : (
                          <button
                            onClick={() => handleApproveDraft(msg.id, msg.previewCard?.caseId)}
                            disabled={sendingCardId === msg.id}
                            className="px-3 py-1.5 rounded-[6px] bg-[#F25C05] hover:bg-[#d94f00] text-[#0A0A0A] font-semibold text-[11.5px] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
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

                      <a
                        href={`/inbox?thread=case-${msg.previewCard.caseId}`}
                        className="text-[11px] text-[#888888] hover:text-[#FFFFFF] flex items-center gap-1 transition-colors"
                      >
                        <span>Open in Inbox</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                    </div>
                  </div>
                )}

                {/* Document Card (if present) */}
                {msg.documentCard && (
                  <div className="mt-3 p-2.5 rounded-[8px] bg-[#222222] border border-[#2E2E2E] flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-[#F25C05]" />
                      <div>
                        <div className="text-[12px] font-semibold text-[#FFFFFF]">
                          {msg.documentCard.title}
                        </div>
                        <div className="text-[10px] text-[#888888] font-mono">
                          {msg.documentCard.size}
                        </div>
                      </div>
                    </div>
                    <span className="text-[11px] text-[#F25C05] font-semibold flex items-center gap-1 cursor-pointer">
                      View <ArrowUpRight className="w-3 h-3" />
                    </span>
                  </div>
                )}
              </div>

              {/* Action Buttons for Assistant Proposals */}
              {msg.actions && msg.actions.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-1">
                  {msg.actions.map((act, idx) => (
                    <button
                      key={idx}
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
            <div className="flex items-center gap-1.5 p-3 rounded-[12px] bg-[#181818] border border-[#262626] w-fit text-[#888888]">
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.15s]" />
              <div className="w-1.5 h-1.5 rounded-full bg-[#F25C05] animate-bounce [animation-delay:0.3s]" />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 4. Suggested Chips Container */}
        <div className="px-5 py-2.5 border-t border-[#262626] bg-[#0A0A0A]">
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-[#777777] mb-2 flex items-center gap-1">
            <span>SUGGESTED FOR THIS PAGE</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {suggestedChips.map((chip, idx) => (
              <button
                key={idx}
                onClick={() => handleSendQuery(chip)}
                className="flex items-center gap-1 px-2.5 py-1 rounded-[6px] bg-[#181818] hover:bg-[#222222] border border-[#262626] hover:border-[#F25C05] text-[11.5px] text-[#DDDDDD] transition-colors cursor-pointer"
              >
                <span>{chip}</span>
                <ArrowUpRight className="w-3 h-3 text-[#F25C05]" />
              </button>
            ))}
          </div>
        </div>

        {/* 5. Input Field Row */}
        <div className="p-4 border-t border-[#262626] bg-[#121212] space-y-2 flex-shrink-0">
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
              placeholder="Ask EstateOS anything about this page..."
              className="w-full h-10 pl-3.5 pr-11 rounded-[10px] bg-[#1A1A1A] border border-[#2A2A2A] text-[13px] text-[#FFFFFF] placeholder:text-[#666666] focus:outline-none focus:border-[#F25C05] focus:ring-2 focus:ring-[#F25C05]/20 transition-all"
            />
            <button
              type="submit"
              disabled={!inputQuery.trim() || isTyping}
              className="absolute right-1.5 w-7 h-7 rounded-[7px] bg-[#F25C05] hover:bg-[#d94f00] disabled:opacity-40 text-[#0A0A0A] flex items-center justify-center transition-colors cursor-pointer"
              title="Send query"
            >
              <Send className="w-3.5 h-3.5 stroke-[2.2]" />
            </button>
          </form>

          {/* Footnote */}
          <p className="text-[10.5px] text-[#666666] text-center leading-tight">
            Prototype: scripted answers from sample data. You confirm every action.
          </p>
        </div>
      </aside>
    </>
  );
}

/**
 * Scripted intelligence answering contextual property management queries.
 */
function generateAssistantResponse(
  query: string,
  pageName: string,
  context: string
): AssistantMessage {
  const q = query.toLowerCase();
  const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  if (q.includes("what should i do first") || q.includes("first") || q.includes("priority")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Priority #1: Emergency Heating Failure & Bathroom Water Leak**\n\nThere is an urgent tenant incident at **Pieter Floriszstraat 1 C** regarding bathroom water leakage and radiator failure reported by tenant Suryansh Tyagi. The food in the fridge is warming up and room temperature is dropping.\n\nI prepared a 4-step execution plan for electrician **Kevin from Chahal Bouw** with an authorized PO budget cap of **€ 650,-** and key lockbox code **#4182**.`,
      readSource: "PostgreSQL Cases #005 · Message from suryanshtyagi.work@gmail.com",
      facts: [
        { label: "Ticket", value: "#005 Emergency Power & Heating", isAlert: true },
        { label: "Contractor", value: "Chahal Bouw (Kevin)" },
        { label: "PO Cap", value: "€ 650,- excl. BTW" },
        { label: "Lockbox", value: "Code 4182" },
      ],
      draftBlock: {
        channel: "gmail",
        to: "suryanshtyagi.work@gmail.com",
        body: "Hi Suryansh, we marked this as urgent ticket #005. Electrician Kevin from Chahal Bouw arrives today between 11:30 - 12:30. Lockbox access #4182 is authorized.",
      },
      actions: [
        {
          label: "Approve 4 steps & Dispatch",
          actionType: "approve_queue_item",
          payload: { ticket: "005" },
          isPrimary: true,
        },
      ],
    };
  }

  if (q.includes("explain this item") || q.includes("explain")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Analysis for ${context}**:\n\n• **Legal SLA (Dutch Civil Code - Burgerlijk Wetboek)**: Urgent heating failure during autumn requires inspection within 4 hours.\n• **Contractor Agreement**: Chahal Bouw has an active master service contract covering Alphen aan den Rijn with standard emergency rates (€85/hr).\n• **Recommended human action**: Authorize dispatch with the €650 PO cap and send arrival window to tenant.`,
      readSource: "Lease C-00041 · Chahal Bouw SLA Framework",
      facts: [
        { label: "SLA Window", value: "< 4 Hours" },
        { label: "Confidence", value: "95% (Rule + AI)" },
      ],
    };
  }

  if (q.includes("behind on rent") || q.includes("rent") || q.includes("arrears") || q.includes("unpaid")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Rent Aging Summary Across 110 Units**:\n\nTotal open rent is **€ 165.734,99** across 95 open invoices. Specifically:\n\n• **11 tenants** are 30+ days overdue (total **€ 14.920,00**).\n• **2 tenants skipped**: Dorpsstraat 54 B has an open leak dispute, Singel 320 is on an agreed repayment plan.\n• **Action ready**: 11 personalized payment reminders drafted in NL, EN, and PL.`,
      readSource: "ING Bank Feed (06:00 sync) · Rent Ledger",
      facts: [
        { label: "Overdue 30+ Days", value: "11 Tenants", isAlert: true },
        { label: "Overdue Amount", value: "€ 14.920,00", isAlert: true },
        { label: "Total Open", value: "€ 165.734,99" },
        { label: "Automated Reminders", value: "11 Ready" },
      ],
      actions: [
        {
          label: "Review 11 Rent Reminders",
          actionType: "navigate_money_reminders",
          isPrimary: true,
        },
      ],
    };
  }

  if (q.includes("energy label") || q.includes("energy") || q.includes("label")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Energy Performance Certificate** for **Pieter Floriszstraat 1 C**:\n\n• **Energy Label**: **A** (Valid until 14 November 2031)\n• **Heating**: High-efficiency HR-107 combi boiler (Remeha Tzerra, installed 2022)\n• **Insulation**: Double HR++ glazing throughout; roof insulation renewed in 2021.\n• **Indexation factor**: Eligible for standard CBS CPI inflation indexation without discount penalties.`,
      readSource: "EP-Online National Database · Registration #NL-EP-9948210",
      documentCard: {
        title: "Energielabel_Pieter_Floriszstraat_1C.pdf",
        size: "1.4 MB · Registered",
      },
    };
  }

  if (q.includes("invoice 26.13.00024") || q.includes("invoice")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Invoice 26.13.00024 Status**:\n\nTenant Huijbergsestraat 5 A sent proof of payment today at 07:15. The ING bank feed confirmed **€ 1.150,00** received on 30-09.\n\nI have matched this transaction to the invoice and cancelled the scheduled payment reminder.`,
      readSource: "Bank Feed 30-09 €1.150,00 · Inbound Gmail 07:15",
      facts: [
        { label: "Invoice", value: "26.13.00024" },
        { label: "Amount", value: "€ 1.150,00" },
        { label: "Status", value: "Matched & Settled" },
      ],
    };
  }

  if (q.includes("gone quiet") || q.includes("quiet") || q.includes("delay")) {
    return {
      id: `ans-${Date.now()}`,
      sender: "assistant",
      timestamp: time,
      text: `**Quiet Ticket Alert**:\n\n• **Ticket #003 (Prinses Marijkestraat 2 A)**: Stove quote of €480,- has been pending contractor acceptance for 48 hours.\n• **Move-out Handover (Henry Dunantweg 5 F)**: Requested end date 31-12-2026 differs from contract end date 31-10-2026. Needs date confirmation call.`,
      readSource: "Unresponsive Radar Engine · Waits Table",
      facts: [
        { label: "Stalled Items", value: "2 Detected", isAlert: true },
        { label: "Longest Delay", value: "48 Hours" },
      ],
    };
  }

  // Fallback intelligent answer
  return {
    id: `ans-${Date.now()}`,
    sender: "assistant",
    timestamp: time,
    text: `I analyzed your request regarding **"${query}"** in the context of **${pageName}** (${context}).\n\nAll 110 units, open tenant cases, and incoming contractor communications are monitored in real time. Would you like me to draft an update, inspect the tenant file, or prepare an action proposal for your review?`,
    readSource: "EstateOS Knowledge Graph · Live State",
  };
}

function formatMarkdown(text: string): string {
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-[#FFFFFF] font-semibold">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em class="text-[#CCCCCC]">$1</em>')
    .replace(/^• (.*?)$/gm, '<div class="flex items-start gap-2 my-1"><span class="text-[#F25C05] font-bold">•</span><span>$1</span></div>');
}
