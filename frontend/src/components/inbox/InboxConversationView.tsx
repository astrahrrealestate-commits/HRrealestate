"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  Clock,
  ExternalLink,
  MoreHorizontal,
  ChevronDown,
  ChevronRight,
  Ticket,
  Reply,
} from "lucide-react";
import { InboxThread, ThreadMessage } from "@/types/inbox";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { UrgentLabel } from "@/components/ui/UrgentLabel";
import { AiInsight } from "@/components/inbox/AiInsight";
import { Composer } from "@/components/inbox/Composer";
import { isUrgent } from "@/lib/selectors";
import { format } from "date-fns";
import { cn } from "@/lib/utils";

interface InboxConversationViewProps {
  thread: InboxThread | null;
  onBack?: () => void;
  onApproveDraft?: (threadId: string, draftText: string, channel: "whatsapp" | "gmail", replyToMessageId?: string) => void;
  onRejectDraft?: (threadId: string) => void;
  onSendManualReply?: (threadId: string, replyText: string, replyToMessageId?: string) => void;
  onMarkDone?: (threadId: string) => void;
  className?: string;
}

export function InboxConversationView({
  thread,
  onBack,
  onApproveDraft,
  onRejectDraft,
  onSendManualReply,
  onMarkDone,
  className,
}: InboxConversationViewProps) {
  const [showEarlier, setShowEarlier] = useState(false);
  const [expandedEnglishMsgIds, setExpandedEnglishMsgIds] = useState<Record<string, boolean>>({});
  const [isSent, setIsSent] = useState(false);
  const [localMessages, setLocalMessages] = useState<ThreadMessage[]>([]);
  const [stagedDraftText, setStagedDraftText] = useState("");
  const [replyingTo, setReplyingTo] = useState<{ id: string; text: string; sender: string } | null>(null);
  const timelineEndRef = useRef<HTMLDivElement>(null);

  // Sync thread messages to local state
  useEffect(() => {
    if (thread) {
      const msgs =
        Array.isArray(thread.messages) && thread.messages.length > 0
          ? thread.messages
          : [
              {
                id: `msg-${thread.id}-single`,
                sender: "tenant" as const,
                senderName: thread.senderName,
                senderContact: thread.senderContact,
                sentAt: thread.receivedAt,
                timeFormatted: thread.relativeTime || "Today",
                body: thread.latestSnippet || thread.subject || "",
                channel: thread.channel,
              },
            ];
      setLocalMessages(msgs);
      setIsSent(thread.status === "approved" || thread.status === "replied");

      const draft =
        thread.draftProposal?.drafts?.[0]?.text ||
        thread.draftProposal?.whatsappDrafts?.[0]?.text ||
        thread.draftProposal?.gmailDrafts?.[0]?.text ||
        "";
      setStagedDraftText(draft);
      setShowEarlier(false);
    }
  }, [thread?.id, thread?.status, thread?.messages?.length]);

  // Scroll to bottom when messages update
  useEffect(() => {
    timelineEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [localMessages.length, isSent]);

  // Keyboard shortcut listener (Section 5.2): 'a' accept, 'r' reject, 'Esc' back
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (
        ["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)
      ) {
        return;
      }

      if (e.key === "a" || e.key === "A") {
        if (thread && stagedDraftText && !isSent) {
          e.preventDefault();
          handleAcceptAndSend(stagedDraftText, thread.channel);
        }
      } else if (e.key === "r" || e.key === "R") {
        if (thread && !isSent) {
          e.preventDefault();
          handleReject();
        }
      } else if (e.key === "Escape") {
        if (onBack) {
          e.preventDefault();
          onBack();
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [thread?.id, stagedDraftText, isSent]);

  if (!thread) {
    return (
      <div
        className={cn(
          "h-full flex items-center justify-center p-8 bg-[var(--pane)] text-center text-[var(--ink-3)] select-none",
          className
        )}
      >
        <p className="text-[14px]">Select a conversation from the list.</p>
      </div>
    );
  }

  const handleToggleEnglish = (msgId: string) => {
    setExpandedEnglishMsgIds((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  const handleAcceptAndSend = (text: string, channel: string, replyToMessageId?: string) => {
    const outboundChannel = (channel === "gmail" ? "gmail" : "whatsapp") as "whatsapp" | "gmail";
    if (onApproveDraft) {
      onApproveDraft(thread.id, text, outboundChannel, replyToMessageId);
    }

    // Add outgoing bubble to timeline immediately (Section 5.2)
    const newOutgoingMsg: ThreadMessage = {
      id: `reply-${Date.now()}`,
      sender: "owner",
      senderName: "Harjot Singh",
      senderContact: "+31 20 000 0001",
      sentAt: new Date().toISOString(),
      timeFormatted: format(new Date(), "HH:mm"),
      body: text,
      channel: outboundChannel,
      replyTo: replyingTo
        ? {
            id: replyingTo.id,
            sender: replyingTo.sender,
            text: replyingTo.text,
          }
        : undefined,
    };
    setLocalMessages((prev) => [...prev, newOutgoingMsg]);
    setIsSent(true);
    setReplyingTo(null);
  };

  const handleReject = () => {
    if (onRejectDraft) {
      onRejectDraft(thread.id);
    }
    setStagedDraftText("");
  };

  const handleUndo = () => {
    setIsSent(false);
    // Remove the temporary outgoing message
    setLocalMessages((prev) => prev.slice(0, -1));
  };

  const urgentThread = isUrgent(thread);
  // Show all messages if user clicked showEarlier, or show latest incoming message PLUS any outgoing replies
  const earlierMessages = localMessages.slice(0, -1);
  const latestMessage = localMessages[localMessages.length - 1];
  const visibleMessages = showEarlier || isSent || localMessages.length <= 2
    ? localMessages
    : latestMessage
    ? [latestMessage]
    : [];

  return (
    <section
      className={cn(
        "flex h-[calc(100dvh-3.5rem)] flex-col bg-[var(--pane)] overflow-hidden select-none",
        className
      )}
    >
      {/* 1. Header (Sticky h-14, Section 5.2) */}
      <div className="h-14 px-4 sm:px-6 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between shrink-0 z-10">
        <div className="flex items-center gap-3 min-w-0">
          {/* Mobile Back Button (Section 5.6) */}
          <button
            type="button"
            onClick={onBack}
            className="md:hidden p-1.5 -ml-1 rounded-[var(--radius-ctl)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
            title="Back to thread list"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          <Avatar name={thread.senderName} channel={thread.channel} size="sm" />

          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="font-heading font-bold text-[16px] sm:text-[18px] text-[var(--ink)] truncate leading-tight">
                {thread.subject || thread.issueTitle || thread.unitLabel}
              </h2>
              {urgentThread && <UrgentLabel />}
            </div>

            <div className="flex items-center gap-2 flex-wrap text-xs text-[var(--ink-3)] leading-normal mt-0.5">
              <span>{thread.senderName}</span>
              <span>·</span>
              <span className="font-medium text-[var(--ink)]">{thread.unitLabel}</span>
              {thread.senderContact && (
                <>
                  <span>·</span>
                  <span className="font-mono text-[11.5px] text-[var(--ink-2)] bg-[var(--selected)] px-1.5 py-0.5 rounded border border-[var(--line)] inline-flex items-center gap-1.5">
                    <span className={cn("inline-block w-1.5 h-1.5 rounded-full", thread.channel === "gmail" ? "bg-[#EA4335]" : "bg-[#25D366]")} />
                    {thread.channel === "gmail" ? (
                      `Gmail: ${thread.senderContact}`
                    ) : (
                      `WhatsApp: ${thread.senderContact}`
                    )}
                  </span>
                </>
              )}
              {thread.ticketNumber && <span>· {thread.ticketNumber}</span>}
            </div>
          </div>
        </div>

        {/* Header Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {thread.ticketNumber && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Ticket className="w-3.5 h-3.5" />}
              className="hidden sm:inline-flex text-xs"
              onClick={() => {}}
            >
              Ticket
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            icon={<Check className="w-3.5 h-3.5" />}
            onClick={() => onMarkDone?.(thread.id)}
            className="text-xs"
          >
            Done
          </Button>

          <Button
            variant="ghost"
            size="sm"
            icon={<MoreHorizontal className="w-4 h-4" />}
            className="px-2"
            title="More actions"
          />
        </div>
      </div>

      {/* 2. Timeline (The only scrolling part, Section 5.2 & 6.2) */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4 space-y-4">
        {/* Simple line for conversation history: only visible if user clicks (user request) */}
        {earlierMessages.length > 0 && (
          <div className="flex items-center gap-3 my-2">
            <div className="flex-1 h-px bg-[var(--line)]" />
            <button
              id="conversation-history-toggle"
              type="button"
              onClick={() => setShowEarlier((prev) => !prev)}
              className="text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] inline-flex items-center gap-1.5 py-1 px-3.5 rounded-full border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] transition-colors cursor-pointer select-none shadow-2xs"
            >
              <Clock className="w-3.5 h-3.5 text-[var(--ink-3)]" />
              <span>
                {showEarlier
                  ? "Hide conversation history"
                  : `Conversation history (${earlierMessages.length} past message${earlierMessages.length > 1 ? "s" : ""})`}
              </span>
              {showEarlier ? (
                <ChevronDown className="w-3 h-3 text-[var(--ink-3)]" />
              ) : (
                <ChevronRight className="w-3 h-3 text-[var(--ink-3)]" />
              )}
            </button>
            <div className="flex-1 h-px bg-[var(--line)]" />
          </div>
        )}

        {/* Message Bubbles with Dynamic Date Group Dividers */}
        {visibleMessages.map((msg, index) => {
          const isOwner = msg.sender === "owner";
          const isDutch =
            thread.detectedLanguage?.includes("nl") ||
            thread.detectedLanguage?.includes("Dutch") ||
            !!msg.bodyEnglish;
          const showEnglish = expandedEnglishMsgIds[msg.id];

          // Determine date label from timeFormatted or sentAt
          const getDayLabel = (m: ThreadMessage) => {
            const tf = m.timeFormatted || "";
            if (tf.toLowerCase().startsWith("yesterday")) return "Yesterday";
            if (tf.toLowerCase().startsWith("today")) return "Today";
            if (m.sentAt) {
              const d = new Date(m.sentAt);
              const now = new Date();
              const isToday = d.toDateString() === now.toDateString();
              const yesterday = new Date(now);
              yesterday.setDate(now.getDate() - 1);
              const isYesterday = d.toDateString() === yesterday.toDateString();
              if (isToday) return "Today";
              if (isYesterday) return "Yesterday";
              return format(d, "EEE d MMM");
            }
            return "Today";
          };

          const currentDayLabel = getDayLabel(msg);
          const prevMsg = index > 0 ? visibleMessages[index - 1] : null;
          const prevDayLabel = prevMsg ? getDayLabel(prevMsg) : null;
          const showDateDivider = index === 0 || currentDayLabel !== prevDayLabel;

          // Time without "Today" or "Yesterday" prefix for the bubble footer
          const displayTime = (msg.timeFormatted || "08:15")
            .replace(/^(today|yesterday)\s*/i, "")
            .trim();

          const englishTranslation =
            msg.bodyEnglish ||
            (msg.body.includes("Hoi beheer")
              ? "Hi management, after turning on the oven the power in the kitchen suddenly went out. Resetting the fuse box unfortunately did not work."
              : msg.body.includes("Nog steeds geen stroom")
              ? "Still no power on the kitchen wall sockets since the short circuit. The fridge is starting to get warm. Can someone come by today? Regards, Pieter"
              : "Still no power on the kitchen sockets since the short circuit. The fridge is starting to warm up. Can someone come today? Regards, Pieter");

          return (
            <React.Fragment key={msg.id}>
              {showDateDivider && (
                <div className="flex items-center gap-3 my-2 text-xs text-[var(--ink-3)]">
                  <div className="flex-1 h-px bg-[var(--line)]" />
                  <span>{currentDayLabel}</span>
                  <div className="flex-1 h-px bg-[var(--line)]" />
                </div>
              )}

              {isOwner ? (
                // Outgoing bubble (right, white with 1px line border)
                <div className="flex flex-col items-end space-y-1">
                  <div className="bg-[var(--pane)] border border-[var(--line)] text-[var(--ink)] rounded-2xl rounded-tr-xs px-4 py-2.5 max-w-[85%] sm:max-w-[75%] shadow-2xs">
                    {msg.replyTo && (
                      <div className="mb-2 pl-2.5 py-1 border-l-2 border-[var(--accent)] bg-[var(--selected)]/70 rounded-r text-xs text-left">
                        <span className="font-semibold text-[11px] text-[var(--accent-ink)] block truncate">
                          Replying to {msg.replyTo.sender}
                        </span>
                        <p className="text-[11.5px] text-[var(--ink-2)] line-clamp-2 italic truncate">
                          "{msg.replyTo.text}"
                        </p>
                      </div>
                    )}
                    <p className="text-[13.5px] leading-relaxed whitespace-pre-line select-text">
                      {msg.body}
                    </p>
                    <div className="flex items-center justify-end gap-1 mt-1 text-[11px] font-mono text-[var(--ink-3)]">
                      <span>{displayTime}</span>
                      <CheckCheck className="w-3.5 h-3.5 text-[var(--ink-3)]" />
                    </div>
                  </div>

                  {/* Inline English toggle for outgoing message if Dutch */}
                  {msg.bodyEnglish && (
                    <div className="pr-2">
                      <button
                        type="button"
                        onClick={() => handleToggleEnglish(msg.id)}
                        className="inline-flex items-center gap-1 text-[11px] text-[var(--ink-3)] hover:text-[var(--ink)] transition-colors cursor-pointer"
                      >
                        {showEnglish ? (
                          <ChevronDown className="w-3 h-3" />
                        ) : (
                          <ChevronRight className="w-3 h-3" />
                        )}
                        <span>{showEnglish ? "Hide English" : "Show English translation"}</span>
                      </button>
                      {showEnglish && (
                        <div className="mt-1 text-xs text-[var(--ink-3)] italic bg-[var(--pane)] border border-[var(--line)]/60 rounded px-2.5 py-1.5 max-w-[85%] text-right">
                          {englishTranslation}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                // Incoming bubble (left, --selected fill, no border)
                <div className="flex flex-col items-start space-y-1 group">
                  <div className="relative bg-[var(--selected)] text-[var(--ink)] rounded-2xl rounded-tl-xs px-4 py-2.5 max-w-[85%] sm:max-w-[75%]">
                    <p className="text-[13.5px] leading-relaxed whitespace-pre-line select-text">
                      {msg.body}
                    </p>
                    <div className="flex items-center justify-between gap-3 text-[11px] font-mono text-[var(--ink-3)] mt-1">
                      <button
                        type="button"
                        onClick={() => {
                          setReplyingTo({
                            id: msg.id,
                            text: msg.body?.slice(0, 80) || "",
                            sender: msg.senderName || thread.senderName || "Tenant",
                          });
                        }}
                        className="inline-flex items-center gap-1 text-[var(--ink-3)] hover:text-[var(--accent-ink)] transition-colors cursor-pointer"
                        title="Quote and reply to this message"
                      >
                        <Reply className="w-3 h-3" />
                        <span>Reply</span>
                      </button>
                      <span>{displayTime}</span>
                    </div>
                  </div>

                  {/* Inline "Show English" translation toggle */}
                  {isDutch && (
                    <div className="pl-2">
                      <button
                        type="button"
                        onClick={() => handleToggleEnglish(msg.id)}
                        className="inline-flex items-center gap-1 text-xs text-[var(--ink-3)] hover:text-[var(--ink)] transition-colors cursor-pointer"
                      >
                        {showEnglish ? (
                          <ChevronDown className="w-3 h-3" />
                        ) : (
                          <ChevronRight className="w-3 h-3" />
                        )}
                        <span>{showEnglish ? "Hide English" : "Show English translation"}</span>
                      </button>

                      {showEnglish && (
                        <div className="mt-1 text-xs text-[var(--ink-3)] italic bg-[var(--pane)] border border-[var(--line)]/60 rounded px-2.5 py-1.5 max-w-[85%]">
                          {englishTranslation}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}

        {/* AiInsight Block (Section 5.2: single block after last incoming message) */}
        <div className="pt-2">
          <AiInsight
            data={
              thread.aiUnderstanding
                ? {
                    ticketNumber: thread.ticketNumber || `#${thread.id.slice(0, 4)}`,
                    urgency: thread.urgency,
                    contractorName: thread.aiUnderstanding.suggestedContractor || "Chahal Bouw",
                    arrivalTime: "Today 11:30 – 12:30",
                    facts: thread.aiUnderstanding.customFacts?.map((f) => ({
                      label: f.label,
                      value: f.value,
                    })),
                  }
                : {
                    ticketNumber: thread.ticketNumber || `#${thread.id.slice(0, 4)}`,
                    urgency: thread.urgency,
                    contractorName: thread.category === "maintenance" ? "Chahal Bouw (Electrician)" : undefined,
                    arrivalTime: thread.category === "maintenance" ? "Today 11:30 – 12:30" : undefined,
                    facts: [
                      { label: "Ticket", value: thread.ticketNumber || `#${thread.id.slice(0, 4)}` },
                      { label: "Category", value: thread.category.toUpperCase() },
                      { label: "Priority", value: (thread.urgency || "normal").toUpperCase(), isAlert: thread.urgency === "emergency" || thread.urgency === "high" },
                      { label: "Unit", value: thread.unitLabel },
                      { label: "Tenant", value: thread.senderName },
                      { label: "Channel", value: thread.channel.toUpperCase() },
                    ],
                  }
            }
          />
        </div>

        <div ref={timelineEndRef} />
      </div>

      {/* 3. Sticky Composer (Section 5.2 & 6.2) */}
      <Composer
        draftText={isSent ? "" : stagedDraftText}
        drafts={
          (thread.channel === "whatsapp"
            ? thread.draftProposal?.whatsappDrafts
            : thread.draftProposal?.gmailDrafts) ||
          thread.draftProposal?.drafts ||
          []
        }
        detectedLanguage={thread.detectedLanguage || "Dutch (detected)"}
        channel={thread.channel}
        replyingTo={replyingTo}
        onClearReplyingTo={() => setReplyingTo(null)}
        onAcceptAndSend={(text, channel, replyId) => {
          handleAcceptAndSend(text, channel, replyId);
          setReplyingTo(null);
        }}
        onReject={handleReject}
        onSendManualReply={(text, channel, replyId) => {
          handleAcceptAndSend(text, channel, replyId);
          setReplyingTo(null);
        }}
        onUndo={handleUndo}
        isSent={isSent}
      />
    </section>
  );
}
