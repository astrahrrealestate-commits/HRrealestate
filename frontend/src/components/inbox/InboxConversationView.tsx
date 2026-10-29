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
  FileText,
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
import { EditTicketModal } from "@/components/maintenance/EditTicketModal";
import { MaintenanceTicket, updateMaintenanceTicket } from "@/lib/api";

interface InboxConversationViewProps {
  thread: InboxThread | null;
  initialDraft?: string;
  onBack?: () => void;
  onApproveDraft?: (threadId: string, draftText: string, channel: "whatsapp" | "gmail", replyToMessageId?: string) => void;
  onRejectDraft?: (threadId: string) => void;
  onSendManualReply?: (threadId: string, replyText: string, replyToMessageId?: string) => void;
  onMarkDone?: (threadId: string) => void;
  className?: string;
}

export function InboxConversationView({
  thread,
  initialDraft,
  onBack,
  onApproveDraft,
  onRejectDraft,
  onSendManualReply,
  onMarkDone,
  className,
}: InboxConversationViewProps) {
  const [showEarlier, setShowEarlier] = useState(false);
  const [isTicketModalOpen, setIsTicketModalOpen] = useState(false);
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
      const isAlreadyReplied = thread.status === "approved" || thread.status === "replied";
      setIsSent(isAlreadyReplied);

      // Resolve channel drafts safely
      const channelDrafts =
        (thread.channel === "whatsapp"
          ? thread.draftProposal?.whatsappDrafts
          : thread.draftProposal?.gmailDrafts) ||
        thread.draftProposal?.drafts ||
        thread.draftProposal?.whatsappDrafts ||
        thread.draftProposal?.gmailDrafts ||
        [];

      const draft = !isAlreadyReplied && channelDrafts.length > 0 ? channelDrafts[0]?.text || "" : "";
      setStagedDraftText(initialDraft || draft);
      setShowEarlier(false);
    }
  }, [thread?.id, thread?.status, thread?.messages?.length, thread?.draftProposal, initialDraft]);

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

    // Only quote if replyingTo is explicitly selected by the user
    const targetReply = replyingTo || null;
    const effectiveReplyId = replyToMessageId || targetReply?.id;
    if (onApproveDraft) {
      onApproveDraft(thread.id, text, outboundChannel, effectiveReplyId);
    }

    const now = new Date();
    const utcHours = String(now.getUTCHours()).padStart(2, "0");
    const utcMins = String(now.getUTCMinutes()).padStart(2, "0");
    // Add outgoing bubble to timeline immediately (Section 5.2)
    const newOutgoingMsg: ThreadMessage = {
      id: `reply-${Date.now()}`,
      sender: "owner",
      senderName: "Harjot Singh",
      senderContact: "+31 20 000 0001",
      sentAt: now.toISOString(),
      timeFormatted: `${utcHours}:${utcMins}`,
      body: text,
      channel: outboundChannel,
      replyTo: targetReply
        ? {
            id: targetReply.id,
            sender: targetReply.sender,
            text: targetReply.text,
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
        "flex h-full flex-1 min-h-0 flex-col bg-[var(--pane)] overflow-hidden",
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

            <div className="flex items-center gap-1.5 flex-wrap text-xs text-[var(--ink-3)] leading-normal mt-0.5">
              <span className="font-semibold text-[var(--ink)]">{thread.unitLabel}</span>
              <span>·</span>
              <span className="text-[var(--ink-2)] truncate max-w-[140px]">{thread.senderName}</span>
              {thread.senderContact && (
                <>
                  <span>·</span>
                  <span className="font-mono text-[11px] text-[var(--ink-2)] bg-[var(--selected)] px-1.5 py-0.5 rounded border border-[var(--line)] inline-flex items-center gap-1.5 truncate max-w-[200px]" title={thread.senderContact}>
                    <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", thread.channel === "gmail" ? "bg-[#EA4335]" : "bg-[#25D366]")} />
                    <span className="truncate">{thread.senderContact}</span>
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
              icon={<Ticket className="w-3.5 h-3.5 text-[var(--accent-ink)]" />}
              className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)]"
              onClick={() => setIsTicketModalOpen(true)}
              title="View and Edit Maintenance Ticket details"
            >
              Ticket {thread.ticketNumber}
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

          // Time formatted in UTC (e.g. 09:35, 09:39)
          const getDisplayTime = (m: ThreadMessage) => {
            if (m.sentAt) {
              const d = new Date(m.sentAt);
              if (!isNaN(d.getTime())) {
                const hh = String(d.getUTCHours()).padStart(2, "0");
                const mm = String(d.getUTCMinutes()).padStart(2, "0");
                return `${hh}:${mm}`;
              }
            }
            return (m.timeFormatted || "08:15")
              .replace(/^(today|yesterday)\s*/i, "")
              .trim();
          };
          const displayTime = getDisplayTime(msg);

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
                      {msg.body?.replace(/^["']|["']$/g, "")}
                    </p>

                    {/* Attachments (Photos & Documents) */}
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className="mt-3 flex flex-col gap-2">
                        {msg.attachments.map((att: any, attIdx: number) => {
                          const isImage =
                            att.type?.startsWith("image/") ||
                            att.mimeType?.startsWith("image/") ||
                            att.name?.match(/\.(jpe?g|png|webp|gif)$/i);
                          const fileUrl = att.url?.startsWith("http")
                            ? att.url
                            : `http://127.0.0.1:8000${att.url}`;
                          return (
                            <div
                              key={att.id || attIdx}
                              className="rounded-xl overflow-hidden border border-[var(--line)] bg-[var(--pane)] shadow-2xs"
                            >
                              {isImage ? (
                                <a
                                  href={att.driveUrl || fileUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block group"
                                  title={att.driveUrl ? "Open in Google Drive" : "View Image"}
                                >
                                  <div className="relative aspect-video max-h-48 overflow-hidden bg-black/5 flex items-center justify-center">
                                    <img
                                      src={fileUrl}
                                      alt={att.name || "Attached photo"}
                                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                                      loading="lazy"
                                    />
                                    {att.driveUrl && (
                                      <div className="absolute top-2 right-2 opacity-90 group-hover:opacity-100 transition-opacity">
                                        <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-800 bg-white/90 backdrop-blur-xs px-2 py-0.5 rounded shadow-2xs border border-emerald-300">
                                          Google Drive
                                        </span>
                                      </div>
                                    )}
                                  </div>
                                  <div className="px-3 py-1.5 flex items-center justify-between text-xs text-[var(--ink-2)] bg-[var(--pane)] border-t border-[var(--line)]">
                                    <span className="truncate max-w-[180px] font-medium group-hover:text-[var(--accent-ink)] transition-colors">{att.name}</span>
                                    <span className="text-[11px] text-[var(--ink-3)] font-mono">{att.size}</span>
                                  </div>
                                </a>
                              ) : (
                                <a
                                  href={att.driveUrl || fileUrl}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="flex items-center gap-2.5 p-2.5 hover:bg-[var(--selected)] transition-colors group"
                                >
                                  <div className="w-8 h-8 rounded-lg bg-red-50 text-red-600 flex items-center justify-center shrink-0 border border-red-200">
                                    <FileText className="w-4 h-4" />
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <p className="text-xs font-semibold text-[var(--ink)] truncate group-hover:text-[var(--accent-ink)]">
                                      {att.name}
                                    </p>
                                    <p className="text-[11px] text-[var(--ink-3)] font-mono">
                                      {att.size} · PDF Document
                                    </p>
                                  </div>
                                  {att.driveUrl && (
                                    <span className="text-[10px] uppercase font-bold tracking-wider text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200">
                                      Google Drive
                                    </span>
                                  )}
                                  <ExternalLink className="w-3.5 h-3.5 text-[var(--ink-3)] group-hover:text-[var(--ink)] shrink-0" />
                                </a>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-3 text-[11px] font-mono text-[var(--ink-3)] mt-1">
                      <button
                        type="button"
                        onClick={() => {
                          setReplyingTo({
                            id: msg.id,
                            text: msg.body?.replace(/^["']|["']$/g, "").slice(0, 80) || "",
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
          isSent
            ? []
            : (thread.channel === "whatsapp"
                ? thread.draftProposal?.whatsappDrafts
                : thread.draftProposal?.gmailDrafts) ||
              thread.draftProposal?.drafts ||
              thread.draftProposal?.whatsappDrafts ||
              thread.draftProposal?.gmailDrafts ||
              []
        }
        detectedLanguage={thread.detectedLanguage || "Dutch (detected)"}
        channel={thread.channel}
        recipientPhone={thread.senderContact}
        recipientEmail={thread.senderContact?.includes("@") ? thread.senderContact : undefined}
        subject={thread.subject}
        externalThreadId={thread.externalThreadId}
        isReply={Boolean(replyingTo || (thread.messages && thread.messages.length > 0))}
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

      {/* In-Place Maintenance Ticket Modal */}
      {thread.ticketNumber && (
        <EditTicketModal
          ticket={{
            id: thread.ticketNumber.replace("#", "m-"),
            ticketNumber: thread.ticketNumber,
            issueTitle: thread.issueTitle || thread.subject || "Maintenance Request",
            unitLabel: thread.unitLabel || "Unassigned Unit",
            tenantName: thread.senderName || "Tenant",
            tenantPhone: thread.senderContact || "+31 6 12 34 41 87",
            category: "electrical",
            contractorName: "Chahal Bouw",
            contractorTrade: "Electrician",
            contractorPhone: "+31 6 88 12 34 56",
            urgency: thread.urgency === "emergency" ? "emergency" : "normal",
            status: "pending_approval",
            slaRemaining: "38m SLA",
            isOverdue: false,
            poBudgetCap: "€ 650",
            reportedAt: thread.relativeTime || "Today",
            notes: thread.caseSummary || "",
            originalMessage: thread.latestSnippet || "",
            contractorDraft: `Beste Kevin (Chahal Bouw), spoedmelding voor ${thread.unitLabel}: ${thread.subject || thread.issueTitle}. Huurder ${thread.senderName} (${thread.senderContact}) is aanwezig. Geautoriseerd budgetplafond: € 650. Sleutelkast pincode: 4182. Gelieve ETA te bevestigen.`,
            tenantDraft: `Beste ${thread.senderName?.split(" ")[0] || "huurder"}, we hebben je melding over ${thread.subject?.toLowerCase() || "het onderhoud"} ontvangen. Onze monteur is geautoriseerd en neemt contact op. Met vriendelijke groet, Harjot`,
          }}
          isOpen={isTicketModalOpen}
          onClose={() => setIsTicketModalOpen(false)}
          onSave={async (updated) => {
            try {
              await updateMaintenanceTicket(updated.ticketNumber, updated);
            } catch {
              // Graceful
            }
            setIsTicketModalOpen(false);
          }}
        />
      )}
    </section>
  );
}
