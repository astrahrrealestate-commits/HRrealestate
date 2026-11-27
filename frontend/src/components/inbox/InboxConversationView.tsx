"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  ArrowLeft,
  Check,
  CheckCheck,
  Clock,
  ExternalLink,
  List,
  MoreHorizontal,
  ChevronDown,
  ChevronRight,
  Ticket,
  Reply,
  FileText,
  AlertTriangle,
  Link2,
  Mail,
} from "lucide-react";
import { InboxThread, ThreadMessage } from "@/types/inbox";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { UrgentLabel } from "@/components/ui/UrgentLabel";
import { formatCategoryLabel } from "@/components/ui/ThreadRow";
import { AiInsight } from "@/components/inbox/AiInsight";
import { Composer } from "@/components/inbox/Composer";
import { isUrgent } from "@/lib/selectors";
import { format } from "date-fns";
import { useLanguage } from "@/context/LanguageContext";
import { cn } from "@/lib/utils";
import { formatClock, localDayNumber, localParts } from "@/lib/clock";
import { EditTicketModal } from "@/components/maintenance/EditTicketModal";
import { TranslationToggle } from "@/components/inbox/TranslationToggle";
import { MaintenanceTicket, updateMaintenanceTicket, linkThreadTenant } from "@/lib/api";
import { BACKEND_BASE_URL } from "@/lib/backend";
import { ExpandableMessageBody } from "@/components/inbox/ExpandableMessageBody";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface InboxConversationViewProps {
  thread: InboxThread | null;
  initialDraft?: string;
  onBack?: () => void;
  onApproveDraft?: (
    threadId: string,
    draftText: string,
    channel: "whatsapp" | "gmail",
    replyToMessageId?: string,
    attachmentIds?: string[]
  ) => void | Promise<boolean>;
  onRejectDraft?: (threadId: string) => void;
  onSendManualReply?: (
    threadId: string,
    replyText: string,
    replyToMessageId?: string,
    attachmentIds?: string[]
  ) => void | Promise<boolean>;
  onMarkDone?: (threadId: string) => void;
  onSnooze?: (threadId: string) => void;
  onMarkUnread?: (threadId: string) => void;
  onTenantLinked?: (threadId: string, tenantName: string) => void;
  showThreadsButton?: boolean;
  showBackOnDesktop?: boolean;
  threadCount?: number;
  isThreadsDrawerOpen?: boolean;
  onToggleThreadsDrawer?: () => void;
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
  onSnooze,
  onMarkUnread,
  onTenantLinked,
  showThreadsButton = false,
  showBackOnDesktop = false,
  threadCount = 0,
  isThreadsDrawerOpen = false,
  onToggleThreadsDrawer,
  className,
}: InboxConversationViewProps) {
  const { t } = useLanguage();
  const [expandedMsgIds, setExpandedMsgIds] = useState<Set<string>>(new Set());
  const [isTicketModalOpen, setIsTicketModalOpen] = useState(false);
  const [isSent, setIsSent] = useState(false);
  const [localMessages, setLocalMessages] = useState<ThreadMessage[]>([]);
  const [stagedDraftText, setStagedDraftText] = useState("");
  const [replyingTo, setReplyingTo] = useState<{ id: string; text: string; sender: string } | null>(null);
  const timelineEndRef = useRef<HTMLDivElement>(null);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [isLinkingTenant, setIsLinkingTenant] = useState(false);
  const [linkSuccessName, setLinkSuccessName] = useState<string | null>(null);

  const handleLinkTenant = async () => {
    if (!thread) return;
    const cId = thread.caseId || thread.id;
    if (!cId) return;
    setIsLinkingTenant(true);
    try {
      const data = await linkThreadTenant(cId, thread.matchedTenant?.id, thread.senderMessageId);
      if (data.ok && data.tenantName) {
        setLinkSuccessName(data.tenantName);
        onTenantLinked?.(thread.id, data.tenantName);
      }
    } catch (err) {
      console.error("Link tenant failed", err);
    } finally {
      setIsLinkingTenant(false);
    }
  };
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const mobileMoreMenuRef = useRef<HTMLDivElement>(null);

  // Close the More actions menu on an outside click, Escape, or when another thread opens.
  useEffect(() => {
    if (!isMoreOpen) return;
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (!moreMenuRef.current?.contains(target) && !mobileMoreMenuRef.current?.contains(target)) {
        setIsMoreOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsMoreOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isMoreOpen]);

  const copyToClipboard = (value?: string) => {
    if (value) void navigator.clipboard?.writeText(value);
    setIsMoreOpen(false);
  };

  const prevThreadIdRef = useRef<string | null>(null);

  // Sync thread messages and pending drafts without resetting expanded emails on 8s polls
  // or falsely marking historical/drafted threads as just-sent.
  useEffect(() => {
    if (!thread) return;
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

    if (prevThreadIdRef.current !== thread.id) {
      prevThreadIdRef.current = thread.id;
      setIsSent(false);
      const lastMsgId = msgs[msgs.length - 1]?.id;
      setExpandedMsgIds(lastMsgId ? new Set([lastMsgId]) : new Set());
      setLinkSuccessName(null);
      setReplyingTo(null);
    }

    const preferredDrafts =
      thread.channel === "whatsapp"
        ? thread.draftProposal?.whatsappDrafts
        : thread.draftProposal?.gmailDrafts;
    const channelDrafts =
      (preferredDrafts && preferredDrafts.length > 0 ? preferredDrafts : null) ||
      (thread.draftProposal?.drafts?.length ? thread.draftProposal.drafts : null) ||
      (thread.draftProposal?.whatsappDrafts?.length ? thread.draftProposal.whatsappDrafts : null) ||
      (thread.draftProposal?.gmailDrafts?.length ? thread.draftProposal.gmailDrafts : null) ||
      [];

    const draft = channelDrafts.length > 0 ? channelDrafts[0]?.text || "" : "";
    setStagedDraftText(initialDraft || draft);
  }, [thread?.id, thread?.status, thread?.messages?.length, thread?.draftProposal, initialDraft]);

  // Scroll only the message pane container (never outer window/body)
  useEffect(() => {
    const container = timelineEndRef.current?.parentElement;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }, [localMessages.length, isSent]);

  // Keyboard shortcut listener: 'Esc' back (never auto-send/reject drafts on bare or modified letter keys)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)) {
        return;
      }
      if (e.key === "Escape" && onBack) {
        e.preventDefault();
        onBack();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onBack]);

  if (!thread) {
    return (
      <div
        className={cn(
          "h-full flex flex-col items-center justify-center p-8 bg-[var(--bg)]/40 text-center text-[var(--ink-3)] select-none gap-3",
          className
        )}
      >
        <div className="w-11 h-11 rounded-full bg-[var(--pane)] border border-[var(--line)] flex items-center justify-center shadow-2xs">
          <Mail className="w-5 h-5 text-[var(--ink-3)]" strokeWidth={1.5} />
        </div>
        <div className="space-y-1">
          <p className="text-[14px] font-semibold text-[var(--ink-2)]">No conversation selected</p>
          <p className="text-[12px] text-[var(--ink-3)]">
            Click a message on the left to open it, or press{" "}
            <kbd className="px-1.5 py-0.5 text-[10.5px] font-mono bg-[var(--pane)] border border-[var(--line)] rounded">j</kbd>{" "}
            /{" "}
            <kbd className="px-1.5 py-0.5 text-[10.5px] font-mono bg-[var(--pane)] border border-[var(--line)] rounded">k</kbd>{" "}
            to browse
          </p>
        </div>
      </div>
    );
  }

  const handleAcceptAndSend = async (
    text: string,
    channel: string,
    replyToMessageId?: string,
    isManual = false,
    attachmentIds?: string[]
  ) => {
    if (!text.trim()) return;
    const outboundChannel = (channel === "gmail" ? "gmail" : "whatsapp") as "whatsapp" | "gmail";

    const targetReply = replyingTo || null;
    const effectiveReplyId = replyToMessageId || targetReply?.id;
    const now = new Date();
    const clockNow = formatClock(now);
    const tempId = `reply-${Date.now()}`;
    const newOutgoingMsg: ThreadMessage = {
      id: tempId,
      sender: "owner",
      senderName: "Harjot Singh",
      senderContact: "+31 20 000 0001",
      sentAt: now.toISOString(),
      timeFormatted: clockNow,
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

    const callback = isManual && onSendManualReply
      ? () => onSendManualReply(thread.id, text, effectiveReplyId, attachmentIds)
      : onApproveDraft
        ? () => onApproveDraft(thread.id, text, outboundChannel, effectiveReplyId, attachmentIds)
        : null;

    if (callback) {
      const ok = await callback();
      if (ok === false) {
        setLocalMessages((prev) => prev.filter((m) => m.id !== tempId));
        setIsSent(false);
      }
    }
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
  const toggleMsgExpanded = (msgId: string) => {
    setExpandedMsgIds((prev) => {
      const next = new Set(prev);
      if (next.has(msgId)) next.delete(msgId);
      else next.add(msgId);
      return next;
    });
  };
  const allExpanded = localMessages.length > 0 && localMessages.every((m) => expandedMsgIds.has(m.id));
  const toggleExpandAll = () => {
    if (allExpanded) {
      const lastId = localMessages[localMessages.length - 1]?.id;
      setExpandedMsgIds(lastId ? new Set([lastId]) : new Set());
    } else {
      setExpandedMsgIds(new Set(localMessages.map((m) => m.id)));
    }
  };

  const renderAttachments = (attachments: ThreadMessage["attachments"]) => {
    if (!attachments || attachments.length === 0) return null;
    return (
      <div className="mt-3 flex flex-col gap-2">
        {attachments.map((att, attIdx) => {
          const isImage =
            att.type?.startsWith("image/") ||
            att.mimeType?.startsWith("image/") ||
            att.name?.match(/\.(jpe?g|png|webp|gif)$/i);
          const fileUrl = att.url?.startsWith("http")
            ? att.url
            : `${BACKEND_BASE_URL}${att.url}`;
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
    );
  };

  return (
    <section
      className={cn(
        "flex h-full flex-1 min-h-0 flex-col bg-[var(--pane)] overflow-hidden",
        className
      )}
    >
      {/* 1. Header: 2-Row Clean Mobile Header + Original Desktop Header */}
      {/* Mobile Header (< 640px) matching approved mockup */}
      <div className="sm:hidden px-3.5 pt-2.5 pb-2.5 border-b border-[var(--line)] bg-[var(--pane)] flex flex-col gap-2 shrink-0 z-10">
        {/* Top Row: Back arrow | Centered Avatar | Ticket Pill */}
        <div className="grid grid-cols-[1fr_auto_1fr] items-center">
          <div className="flex items-center justify-start">
            <button
              type="button"
              onClick={onBack}
              className="p-1.5 -ml-1.5 rounded-full text-[var(--ink)] hover:bg-[var(--selected)] transition-colors cursor-pointer"
              title="Back to thread list"
              aria-label="Back to thread list"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
          </div>

          <Avatar name={thread.senderName} channel={thread.channel} size="default" />

          <div className="flex items-center justify-end">
            {thread.category === "maintenance" && thread.ticketNumber ? (
              <button
                type="button"
                onClick={() => setIsTicketModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold text-[var(--ink)] bg-[#F1F5F9] hover:bg-[#E2E8F0] border border-[var(--line)] transition-colors cursor-pointer"
                title="View and Edit Maintenance Ticket details"
              >
                <Ticket className="w-3.5 h-3.5 text-[var(--ink-2)]" />
                <span>Ticket</span>
              </button>
            ) : (
              <span />
            )}
          </div>
        </div>

        {/* Bottom Row: Contact Name + Full Subject + Unit/Ticket | [Done] [More] square pills */}
        <div className="flex items-start justify-between gap-2 min-w-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 flex-wrap min-w-0">
              <h2 className="font-heading font-bold text-[16px] text-[var(--ink)] break-words leading-snug">
                {thread.subject || thread.issueTitle || thread.senderName || thread.unitLabel}
              </h2>
              {urgentThread && <UrgentLabel />}
            </div>
            <p className="text-[12px] text-[var(--ink-3)] leading-tight mt-0.5 break-words">
              {[thread.senderName, thread.unitLabel, thread.ticketNumber].filter(Boolean).join(" · ")}
            </p>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => onMarkDone?.(thread.id)}
              className="w-8 h-8 rounded-[10px] bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[var(--ink)] flex items-center justify-center transition-colors cursor-pointer"
              title="Mark thread done"
              aria-label="Mark done"
            >
              <Check className="w-4 h-4 stroke-[2.2]" />
            </button>

            <div className="relative" ref={mobileMoreMenuRef}>
              <button
                type="button"
                onClick={() => setIsMoreOpen((open) => !open)}
                className="w-8 h-8 rounded-[10px] bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[var(--ink)] flex items-center justify-center transition-colors cursor-pointer"
                title="More actions"
                aria-haspopup="menu"
                aria-expanded={isMoreOpen}
              >
                <MoreHorizontal className="w-4 h-4" />
              </button>
              {isMoreOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-full mt-1 z-30 min-w-[220px] rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] shadow-md py-1 text-[13px]"
                >
                  {thread.senderContact && (
                    <div className="px-3 py-1.5 border-b border-[var(--line)] text-[11px] text-[var(--ink-3)] flex items-center gap-1.5 font-mono truncate">
                      <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", thread.channel === "gmail" ? "bg-[#EA4335]" : "bg-[#25D366]")} />
                      <span className="truncate">{thread.senderContact}</span>
                    </div>
                  )}
                  {[
                    { label: "Copy ticket number", value: thread.ticketNumber },
                    { label: "Copy sender contact", value: thread.senderContact },
                  ].map((item) => (
                    <button
                      key={item.label}
                      type="button"
                      role="menuitem"
                      disabled={!item.value}
                      onClick={() => copyToClipboard(item.value)}
                      className="w-full text-left px-3 py-1.5 text-[var(--ink)] hover:bg-[var(--selected)] disabled:text-[var(--ink-3)] disabled:hover:bg-transparent cursor-pointer disabled:cursor-not-allowed"
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Desktop Header (>= 640px) — slim 2-line header without duplicate contact/ticket pills */}
      <div className="hidden sm:flex min-h-12 px-4 lg:px-5 py-2 border-b border-[var(--line)] bg-[var(--pane)] items-center justify-between gap-3 shrink-0 z-10">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          {showBackOnDesktop && onBack && (
            <>
              <button
                type="button"
                onClick={onBack}
                className="hidden lg:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--bg)] hover:bg-[var(--selected)] text-[var(--ink)] text-[12px] font-medium transition-colors cursor-pointer shrink-0"
                title="Back to all conversations"
              >
                <ArrowLeft className="w-3.5 h-3.5 text-[var(--ink-2)]" />
                <span>{t("All conversations", "Alle gesprekken")}</span>
              </button>
              <span className="hidden lg:inline-block h-5 w-px bg-[var(--line)] shrink-0" />
            </>
          )}
          {showThreadsButton && onToggleThreadsDrawer && (
            <>
              <button
                type="button"
                onClick={onToggleThreadsDrawer}
                className={cn(
                  "hidden lg:inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[var(--radius-ctl)] border text-[12px] font-semibold transition-colors cursor-pointer shrink-0",
                  isThreadsDrawerOpen
                    ? "bg-[var(--ink)] text-[var(--pane)] border-[var(--ink)]"
                    : "bg-[var(--bg)] hover:bg-[var(--selected)] text-[var(--ink)] border-[var(--line)]"
                )}
                title={isThreadsDrawerOpen ? "Hide threads list" : "Switch conversation thread"}
              >
                <List className="w-3.5 h-3.5" />
                <span>Threads ({threadCount})</span>
              </button>
              <span className="hidden lg:inline-block h-5 w-px bg-[var(--line)] shrink-0" />
            </>
          )}
          <Avatar name={thread.senderName} channel={thread.channel} size="sm" className="shrink-0" />

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <h2
                className="font-heading font-bold text-[15px] lg:text-[16px] text-[var(--ink)] truncate leading-snug min-w-0"
                title={thread.subject || thread.issueTitle || thread.unitLabel}
              >
                {thread.subject || thread.issueTitle || thread.unitLabel}
              </h2>
              {urgentThread && <UrgentLabel />}
            </div>

            <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--ink-3)] leading-tight mt-0.5 min-w-0 overflow-hidden">
              {thread.unitLabel && thread.unitLabel !== thread.senderContact && (
                <>
                  <span className="font-medium text-[var(--ink-2)] truncate max-w-[140px]">{thread.unitLabel}</span>
                  <span className="shrink-0">·</span>
                </>
              )}
              {thread.senderName && thread.senderName !== thread.senderContact && (
                <>
                  <span className="text-[var(--ink-2)] truncate max-w-[130px]">{thread.senderName}</span>
                  <span className="shrink-0">·</span>
                </>
              )}
              {thread.senderContact && (
                <span className="font-mono text-[11px] text-[var(--ink-2)] inline-flex items-center gap-1.5 truncate min-w-0" title={thread.senderContact}>
                  <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", thread.channel === "gmail" ? "bg-[#EA4335]" : "bg-[#25D366]")} />
                  <span className="truncate">{thread.senderContact}</span>
                </span>
              )}
              {thread.recipientRoleDetail && thread.recipientRoleDetail !== "Contact" && (
                <span className="inline-flex items-center px-1.5 py-0.2 rounded border border-[var(--line)] bg-[var(--bg)] text-[10px] font-semibold text-[var(--ink-2)] shrink-0">
                  {thread.recipientRoleDetail}
                </span>
              )}
              {(() => {
                const catLabel = formatCategoryLabel(thread.category);
                if (!catLabel || catLabel.toLowerCase() === thread.recipientRoleDetail?.toLowerCase()) return null;
                return (
                  <span className="inline-flex items-center px-1.5 py-0.2 rounded border border-[var(--line)] bg-[var(--selected)]/60 text-[10px] font-medium text-[var(--ink-2)] shrink-0">
                    {catLabel}
                  </span>
                );
              })()}
              {thread.ticketNumber && !(thread.category === "maintenance" && thread.ticketNumber) && (
                <span className="shrink-0">· {thread.ticketNumber}</span>
              )}
            </div>
          </div>
        </div>

        {/* Desktop Header Actions */}
        <div className="flex items-center gap-1 shrink-0">
          {thread.category === "maintenance" && thread.ticketNumber && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Ticket className="w-3.5 h-3.5 text-[var(--accent-ink)]" />}
              className="text-xs border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] px-2.5 h-7.5 whitespace-nowrap"
              onClick={() => setIsTicketModalOpen(true)}
              title="View and Edit Maintenance Ticket details"
            >
              <span>{thread.ticketNumber}</span>
            </Button>
          )}

          {onSnooze && (
            <Button
              variant="ghost"
              size="sm"
              icon={<Clock className="w-3.5 h-3.5" />}
              onClick={() => onSnooze(thread.id)}
              className="text-xs px-2 h-7.5"
              title="Snooze until tomorrow"
            >
              <span className="hidden 2xl:inline">Snooze</span>
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            icon={<Check className="w-3.5 h-3.5" />}
            onClick={() => onMarkDone?.(thread.id)}
            className="text-xs px-2 h-7.5"
            title="Mark thread done"
          >
            Done
          </Button>

          <div className="relative" ref={moreMenuRef}>
            <Button
              variant="ghost"
              size="sm"
              icon={<MoreHorizontal className="w-4 h-4" />}
              className="px-2 h-8"
              title="More actions"
              aria-haspopup="menu"
              aria-expanded={isMoreOpen}
              onClick={() => setIsMoreOpen((open) => !open)}
            />
            {isMoreOpen && (
              <div
                role="menu"
                className="absolute right-0 top-full mt-1 z-20 min-w-[220px] rounded-[var(--radius-ctl)] border border-[var(--line)] bg-[var(--pane)] shadow-md py-1 text-[13px]"
              >
                {thread.senderContact && (
                  <div className="px-3 py-1.5 border-b border-[var(--line)] text-[11px] text-[var(--ink-3)] flex items-center gap-1.5 font-mono truncate">
                    <span className={cn("inline-block w-1.5 h-1.5 rounded-full shrink-0", thread.channel === "gmail" ? "bg-[#EA4335]" : "bg-[#25D366]")} />
                    <span className="truncate">{thread.senderContact}</span>
                  </div>
                )}
                {onMarkUnread && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      onMarkUnread(thread.id);
                      setIsMoreOpen(false);
                    }}
                    className="w-full text-left px-3 py-1.5 text-[var(--ink)] hover:bg-[var(--selected)] cursor-pointer"
                  >
                    Mark as unread
                  </button>
                )}
                {[
                  { label: "Copy ticket number", value: thread.ticketNumber },
                  { label: "Copy sender contact", value: thread.senderContact },
                ].map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    role="menuitem"
                    disabled={!item.value}
                    onClick={() => copyToClipboard(item.value)}
                    className="w-full text-left px-3 py-1.5 text-[var(--ink)] hover:bg-[var(--selected)] disabled:text-[var(--ink-3)] disabled:hover:bg-transparent cursor-pointer disabled:cursor-not-allowed"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 2. Timeline (The only scrolling part, Section 5.2 & 6.2) */}
      <div className="flex-1 overflow-y-auto px-3 sm:px-6 py-3 sm:py-4 space-y-3 sm:space-y-4">
        {/* Unregistered Sender Warning Banner */}
        {thread.isUnregisteredSender && thread.matchedTenant && !linkSuccessName && (
          <div className="mb-3 p-3 rounded-[var(--radius-ctl)] bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/60 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5 shadow-2xs">
            <div className="flex items-start gap-2.5 text-[12px] text-amber-900 dark:text-amber-200">
              <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Unregistered Sender: </span>
                <span className="font-mono bg-amber-100 dark:bg-amber-900/50 px-1 py-0.5 rounded text-[11px]">{thread.senderContact}</span> is not on the lease for{" "}
                <span className="font-semibold">{thread.matchedTenant.unit}</span>.
                <div className="text-[11px] text-amber-700 dark:text-amber-300 mt-0.5">
                  Registered Leaseholder: <span className="font-semibold">{thread.matchedTenant.name}</span>
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={handleLinkTenant}
              disabled={isLinkingTenant}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[11.5px] font-semibold rounded-[var(--radius-ctl)] bg-amber-600 hover:bg-amber-700 text-white shadow-2xs transition-colors shrink-0 cursor-pointer disabled:opacity-50"
            >
              <Link2 className="w-3.5 h-3.5" />
              <span>{isLinkingTenant ? "Linking..." : `Link to ${thread.matchedTenant.name}`}</span>
            </button>
          </div>
        )}

        {linkSuccessName && (
          <div className="mb-3 p-2.5 rounded-[var(--radius-ctl)] bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/60 flex items-center gap-2 text-[12px] text-emerald-800 dark:text-emerald-200 shadow-2xs">
            <Check className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>Successfully linked <span className="font-mono">{thread.senderContact}</span> as a secondary contact to <strong>{linkSuccessName}</strong>.</span>
          </div>
        )}
        {/* Gmail-style Expand/Collapse All strip for multi-message threads */}
        {localMessages.length > 1 && (
          <div className="flex items-center justify-between gap-2 pb-1">
            <span className="text-[11.5px] font-medium text-[var(--ink-3)]">
              {localMessages.length} messages in thread
            </span>
            <button
              type="button"
              onClick={toggleExpandAll}
              className="text-[11.5px] font-semibold text-[var(--accent-ink)] hover:underline cursor-pointer"
            >
              {allExpanded ? "Collapse older" : "Expand all"}
            </button>
          </div>
        )}

        {/* Message Cards: Older messages collapse to 1-line Gmail headers; click to open one by one */}
        {localMessages.map((msg, index) => {
          const isOwner = msg.sender === "owner";
          const isExpanded = expandedMsgIds.has(msg.id) || localMessages.length === 1;

          // Determine date label from timeFormatted or sentAt
          const getDayLabel = (m: ThreadMessage) => {
            const tf = m.timeFormatted || "";
            if (tf.toLowerCase().startsWith("yesterday")) return "Yesterday";
            if (tf.toLowerCase().startsWith("today")) return "Today";
            if (m.sentAt) {
              const d = new Date(m.sentAt);
              const ago = localDayNumber(new Date()) - localDayNumber(d);
              if (ago === 0) return "Today";
              if (ago === 1) return "Yesterday";
              const local = localParts(d);
              return `${local.weekday} ${local.day} ${MONTHS[local.month - 1]}`;
            }
            return "Today";
          };

          const currentDayLabel = getDayLabel(msg);
          const prevMsg = index > 0 ? localMessages[index - 1] : null;
          const prevDayLabel = prevMsg ? getDayLabel(prevMsg) : null;
          const showDateDivider = index === 0 || currentDayLabel !== prevDayLabel;

          // Time on the company's local clock, 24 h (e.g. 09:35)
          const getDisplayTime = (m: ThreadMessage) => {
            if (m.sentAt) {
              const d = new Date(m.sentAt);
              if (!isNaN(d.getTime())) return formatClock(d);
            }
            return (m.timeFormatted || "")
              .replace(/^(today|yesterday)\s*/i, "")
              .trim();
          };
          const displayTime = getDisplayTime(msg);

          if (!isExpanded) {
            const oneLineSnippet = (msg.body || "").replace(/\s+/g, " ").trim();
            return (
              <React.Fragment key={msg.id}>
                {showDateDivider && (
                  <div className="flex items-center gap-3 my-1.5 text-xs text-[var(--ink-3)]">
                    <div className="flex-1 h-px bg-[var(--line)]" />
                    <span>{currentDayLabel}</span>
                    <div className="flex-1 h-px bg-[var(--line)]" />
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => toggleMsgExpanded(msg.id)}
                  className="w-full px-3.5 py-2.5 rounded-[10px] border border-[var(--line)] bg-[var(--bg)]/50 hover:bg-[var(--selected)]/70 flex items-center justify-between gap-3 text-left transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <Avatar name={msg.senderName || thread.senderName} channel={msg.channel} size="sm" className="shrink-0" />
                    <span className="text-[12.5px] font-semibold text-[var(--ink)] shrink-0 max-w-[140px] truncate">
                      {isOwner ? "You" : (msg.senderName || thread.senderName)}
                    </span>
                    <span className="text-[12.5px] text-[var(--ink-3)] truncate min-w-0">
                      {oneLineSnippet}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 text-[11px] font-mono text-[var(--ink-3)]">
                    <span>{displayTime}</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </div>
                </button>
              </React.Fragment>
            );
          }

          return (
            <React.Fragment key={msg.id}>
              {showDateDivider && (
                <div className="flex items-center gap-3 my-2 text-xs text-[var(--ink-3)]">
                  <div className="flex-1 h-px bg-[var(--line)]" />
                  <span>{currentDayLabel}</span>
                  <div className="flex-1 h-px bg-[var(--line)]" />
                </div>
              )}

              {localMessages.length > 1 && index < localMessages.length - 1 && (
                <button
                  type="button"
                  onClick={() => toggleMsgExpanded(msg.id)}
                  className="text-[11px] text-[var(--ink-3)] hover:text-[var(--ink)] inline-flex items-center gap-1 cursor-pointer mb-0.5"
                >
                  <ChevronDown className="w-3 h-3" />
                  <span>Collapse {isOwner ? "your reply" : (msg.senderName || "message")} · {displayTime}</span>
                </button>
              )}

              {msg.channel === "gmail" ? (
                <article className="rounded-xl border border-[var(--line)] bg-[var(--pane)] shadow-2xs overflow-hidden min-w-0">
                  <div className="px-4 py-3 border-b border-[var(--line)] bg-[var(--bg)]/45 space-y-1">
                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Avatar
                          name={isOwner ? "Harjot Singh" : (msg.senderName || thread.senderName)}
                          channel={msg.channel}
                          size="sm"
                          className="shrink-0"
                        />
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap text-[12.5px]">
                            <bdi className="font-semibold text-[var(--ink)] truncate">
                              {isOwner ? "Harjot Singh" : msg.senderName}
                            </bdi>
                            {msg.senderContact && msg.senderContact !== msg.senderName && (
                              <bdi className="text-[11.5px] text-[var(--ink-3)] font-mono break-all">
                                &lt;{msg.senderContact}&gt;
                              </bdi>
                            )}
                            {isOwner && (
                              <span className="inline-flex items-center px-1.5 py-0.2 rounded border border-emerald-200 bg-emerald-50 text-[10px] font-semibold text-emerald-700">
                                Sent
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2.5 shrink-0 text-[11px] font-mono text-[var(--ink-3)] pt-0.5">
                        <span>{currentDayLabel} · {displayTime}</span>
                        {!isOwner && (
                          <button
                            type="button"
                            onClick={() => {
                              setReplyingTo({
                                id: msg.id,
                                text: msg.body?.replace(/^["']|["']$/g, "").slice(0, 80) || "",
                                sender: msg.senderName || thread.senderName || "Sender",
                              });
                            }}
                            className="inline-flex items-center gap-1 font-sans font-medium text-[var(--ink-3)] hover:text-[var(--accent-ink)] transition-colors cursor-pointer"
                            title="Reply to this email"
                          >
                            <Reply className="w-3.5 h-3.5" />
                            <span>Reply</span>
                          </button>
                        )}
                      </div>
                    </div>

                    <div className="pl-9 text-[11.5px] text-[var(--ink-3)] flex flex-wrap gap-x-4 gap-y-0.5">
                      {msg.to && msg.to.length > 0 && (
                        <span className="truncate max-w-full">
                          <strong className="font-medium text-[var(--ink-2)]">To:</strong> {msg.to.join(", ")}
                        </span>
                      )}
                      {msg.cc && msg.cc.length > 0 && (
                        <span className="truncate max-w-full">
                          <strong className="font-medium text-[var(--ink-2)]">Cc:</strong> {msg.cc.join(", ")}
                        </span>
                      )}
                      {msg.subject && (index === 0 || (prevMsg?.subject && msg.subject !== prevMsg.subject)) && (
                        <span className="truncate max-w-full">
                          <strong className="font-medium text-[var(--ink-2)]">Subject:</strong> {msg.subject}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="px-4 py-3.5 space-y-2.5 min-w-0">
                    {msg.replyTo && (
                      <div className="pl-2.5 py-1 border-l-2 border-[var(--accent)] bg-[var(--selected)]/70 rounded-r text-xs">
                        <span className="font-semibold text-[11px] text-[var(--accent-ink)] block truncate">
                          Replying to {msg.replyTo.sender}
                        </span>
                        <p className="text-[11.5px] text-[var(--ink-2)] line-clamp-2 italic truncate">
                          &ldquo;{msg.replyTo.text}&rdquo;
                        </p>
                      </div>
                    )}
                    <ExpandableMessageBody body={msg.body} bodyHtml={msg.bodyHtml} isOwner={false} />
                    {renderAttachments(msg.attachments)}
                    <TranslationToggle text={msg.body} language={msg.language} cachedEnglish={msg.bodyEnglish} cachedDutch={msg.bodyDutch} />
                  </div>
                </article>
              ) : isOwner ? (
                // Outgoing WhatsApp bubble (right, vibrant blue on mobile per mockup, crisp white with border on desktop)
                <div className="flex flex-col items-end space-y-1 min-w-0">
                  <div className="bg-[#1a73e8] sm:bg-[var(--pane)] sm:border sm:border-[var(--line)] text-white sm:text-[var(--ink)] rounded-2xl rounded-tr-xs px-3.5 sm:px-4 py-2.5 max-w-[85%] sm:max-w-[75%] min-w-0 overflow-hidden shadow-2xs">
                    {msg.replyTo && (
                      <div className="mb-2 pl-2.5 py-1 border-l-2 border-white/60 sm:border-[var(--accent)] bg-white/15 sm:bg-[var(--selected)]/70 rounded-r text-xs text-left">
                        <span className="font-semibold text-[11px] text-white sm:text-[var(--accent-ink)] block truncate">
                          Replying to {msg.replyTo.sender}
                        </span>
                        <p className="text-[11.5px] text-white/90 sm:text-[var(--ink-2)] line-clamp-2 italic truncate">
                          "{msg.replyTo.text}"
                        </p>
                      </div>
                    )}
                    <ExpandableMessageBody body={msg.body} bodyHtml={msg.bodyHtml} isOwner={true} />
                    {renderAttachments(msg.attachments)}
                    <div className="flex items-center justify-end gap-1 mt-1 text-[11px] font-mono text-white/80 sm:text-[var(--ink-3)]">
                      <span>{displayTime}</span>
                      <CheckCheck className="w-3.5 h-3.5 text-sky-200 sm:text-[var(--ink-3)]" />
                    </div>
                  </div>

                  <TranslationToggle text={msg.body} language={msg.language} cachedEnglish={msg.bodyEnglish} cachedDutch={msg.bodyDutch} align="right" />
                </div>
              ) : (
                // Incoming WhatsApp bubble (left, --selected fill, no border)
                <div className="flex flex-col items-start space-y-1 group min-w-0">
                  {/* The name is sender-chosen: it truncates on its own line box and never pushes the address away. */}
                  <div className="flex flex-wrap items-baseline gap-x-1.5 px-1 max-w-[85%] sm:max-w-[75%] text-[11px] text-[var(--ink-3)]">
                    <bdi className="min-w-0 max-w-full truncate font-semibold text-[var(--ink-2)]">{msg.senderName}</bdi>
                    {msg.senderContact && msg.senderContact !== msg.senderName && (
                      <bdi className="max-w-full break-all">&lt;{msg.senderContact}&gt;</bdi>
                    )}
                  </div>
                  <div
                    className={cn(
                      "relative bg-[var(--selected)] text-[var(--ink)] rounded-2xl rounded-tl-xs px-4 py-2.5 min-w-0 overflow-hidden",
                      msg.bodyHtml ? "w-full max-w-[92%] sm:max-w-[85%]" : "max-w-[85%] sm:max-w-[75%]"
                    )}
                  >
                    <ExpandableMessageBody body={msg.body} bodyHtml={msg.bodyHtml} isOwner={false} />
                    {renderAttachments(msg.attachments)}
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

                  <TranslationToggle text={msg.body} language={msg.language} cachedEnglish={msg.bodyEnglish} cachedDutch={msg.bodyDutch} />
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
                    ticketNumber: thread.ticketNumber,
                    urgency: thread.urgency,
                    contractorName: thread.aiUnderstanding.suggestedContractor || undefined,
                    facts: thread.aiUnderstanding.customFacts?.map((f) => ({
                      label: f.label,
                      value: f.value,
                      isAlert: f.isAlert,
                    })),
                  }
                : {
                    ticketNumber: thread.ticketNumber,
                    urgency: thread.urgency,
                    facts: [
                      { label: "Ticket", value: thread.ticketNumber || "—" },
                      { label: "Category", value: thread.category.toUpperCase() },
                      { label: "Priority", value: (thread.urgency || "normal").toUpperCase(), isAlert: thread.urgency === "emergency" || thread.urgency === "high" },
                      ...(thread.unitLabel ? [{ label: "Unit", value: thread.unitLabel }] : []),
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
        threadKey={thread.id}
        caseId={thread.caseId || thread.id}
        targetMessageId={thread.messages?.[thread.messages.length - 1]?.id}
        draftText={isSent ? "" : stagedDraftText}
        drafts={
          isSent
            ? []
            : (() => {
                const preferred =
                  thread.channel === "whatsapp"
                    ? thread.draftProposal?.whatsappDrafts
                    : thread.draftProposal?.gmailDrafts;
                if (preferred && preferred.length > 0) return preferred;
                if (thread.draftProposal?.drafts?.length) return thread.draftProposal.drafts;
                if (thread.draftProposal?.whatsappDrafts?.length) return thread.draftProposal.whatsappDrafts;
                if (thread.draftProposal?.gmailDrafts?.length) return thread.draftProposal.gmailDrafts;
                return [];
              })()
        }
        draftPersona={isSent ? undefined : thread.draftProposal?.persona}
        detectedLanguage={thread.detectedLanguage || "Dutch (detected)"}
        channel={thread.channel}
        recipientPhone={thread.senderContact}
        recipientEmail={thread.senderContact?.includes("@") ? thread.senderContact : undefined}
        subject={thread.subject}
        externalThreadId={thread.externalThreadId}
        isReply={Boolean(replyingTo || (thread.messages && thread.messages.length > 0))}
        replyingTo={replyingTo}
        onClearReplyingTo={() => setReplyingTo(null)}
        onAcceptAndSend={(text, channel, replyId, attachmentIds) => {
          void handleAcceptAndSend(text, channel, replyId, false, attachmentIds);
        }}
        onReject={handleReject}
        onSendManualReply={(text, channel, replyId, attachmentIds) => {
          void handleAcceptAndSend(text, channel, replyId, true, attachmentIds);
        }}
        onUndo={handleUndo}
        isSent={isSent}
      />

      {/* In-Place Maintenance Ticket Modal */}
      {thread.category === "maintenance" && thread.ticketNumber && (
        <EditTicketModal
          ticket={{
            id: thread.caseId || thread.id,
            ticketNumber: thread.ticketNumber,
            issueTitle: thread.issueTitle || thread.subject || "Maintenance Request",
            unitLabel: thread.unitLabel || "Unassigned Unit",
            tenantName: thread.senderName || "Tenant",
            tenantPhone: thread.senderContact || "",
            category: "appliance",
            contractorName: thread.aiUnderstanding?.suggestedContractor || "",
            contractorTrade: "",
            urgency: thread.urgency === "emergency" ? "emergency" : "normal",
            status: "pending_approval",
            slaRemaining: "",
            isOverdue: false,
            poBudgetCap: "",
            reportedAt: thread.relativeTime || "Today",
            notes: thread.caseSummary || "",
            originalMessage: thread.latestSnippet || "",
            contractorDraft: "",
            tenantDraft: thread.draftProposal?.drafts?.[0]?.text || "",
          }}
          isOpen={isTicketModalOpen}
          onClose={() => setIsTicketModalOpen(false)}
          onSave={async (updated) => {
            try {
              await updateMaintenanceTicket(updated.id || updated.ticketNumber, updated);
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
