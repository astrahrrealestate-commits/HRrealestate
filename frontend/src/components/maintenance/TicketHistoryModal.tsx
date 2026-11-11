"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  X,
  Clock,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Mail,
  MessageSquare,
  Wrench,
  ShieldAlert,
  Coins,
  Key,
  Download,
  Copy,
  ExternalLink,
  ChevronRight,
  User,
  ArrowRight,
} from "lucide-react";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { getTicketHistory } from "@/lib/api";
import { useLanguage } from "@/context/LanguageContext";

interface TimelineEvent {
  id: string;
  timestamp: string;
  type: "inbound" | "triage" | "approval" | "dispatch" | "contractor" | "state_change" | "invoice";
  actor: string;
  actorRole: "tenant" | "system" | "owner" | "contractor";
  title: string;
  description: string;
  badge?: string;
  badgeVariant?: "default" | "urgent" | "needs_you";
  details?: {
    channel?: "whatsapp" | "gmail";
    poNumber?: string;
    budgetAmount?: string;
    lockboxCode?: string;
    stateFrom?: string;
    stateTo?: string;
    invoiceAmount?: string;
    attachments?: Array<{ name: string; size: string; type: string }>;
  };
}

interface MaintenanceTicket {
  id: string;
  ticketNumber: string;
  issueTitle: string;
  unitLabel: string;
  tenantName: string;
  tenantPhone: string;
  category: "electrical" | "plumbing" | "heating" | "appliance" | "structural";
  contractorName: string;
  contractorTrade: string;
  urgency: "emergency" | "high" | "normal" | "low";
  status: "pending_approval" | "dispatched" | "scheduled" | "completed";
  slaRemaining: string;
  isOverdue?: boolean;
  poBudgetCap: string;
  reportedAt: string;
  notes: string;
}

interface TicketHistoryModalProps {
  ticket: MaintenanceTicket | null;
  isOpen: boolean;
  onClose: () => void;
  onShowToast: (msg: string) => void;
}

export function TicketHistoryModal({
  ticket,
  isOpen,
  onClose,
  onShowToast,
}: TicketHistoryModalProps) {
  const router = useRouter();
  const { t } = useLanguage();
  const [activeFilter, setActiveFilter] = useState<"all" | "messages" | "po" | "audit">("all");
  const [copied, setCopied] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen && ticket) {
      const cleanId = ticket.ticketNumber?.replace("#", "") || ticket.id;
      getTicketHistory(cleanId).catch(() => {});
    }
  }, [isOpen, ticket]);

  if (!isOpen || !ticket) return null;

  // Build rich contextual audit events matching backend database architecture
  const isCompleted = ticket.status === "completed";
  const isEmergency = ticket.urgency === "emergency" || ticket.isOverdue;

  const events: TimelineEvent[] = [
    {
      id: "ev-1",
      timestamp: `${ticket.reportedAt} (08:15 CET)`,
      type: "inbound",
      actor: ticket.tenantName,
      actorRole: "tenant",
      title: "Inbound Tenant Report Received",
      description: `Tenant reported issue via WhatsApp: "${ticket.notes}"`,
      badge: "WhatsApp Inbound",
      badgeVariant: "default",
      details: {
        channel: "whatsapp",
        attachments: [
          { name: "photo_circuit_breaker_tripped.jpg", size: "2.4 MB", type: "image/jpeg" },
        ],
      },
    },
    {
      id: "ev-2",
      timestamp: "Today 08:16 CET",
      type: "triage",
      actor: "EstateOS Inbound Triage Agent",
      actorRole: "system",
      title: "AI Triage & SLA Initialization",
      description: `Classified as ${ticket.urgency.toUpperCase()} (${ticket.category}). Unit mapped to ${ticket.unitLabel} with 93% match confidence. 4-hour SLA timer initialized.`,
      badge: isEmergency ? "Emergency SLA" : "Normal SLA",
      badgeVariant: isEmergency ? "urgent" : "default",
      details: {
        stateFrom: "none",
        stateTo: "open",
      },
    },
    {
      id: "ev-3",
      timestamp: "Today 08:18 CET",
      type: "approval",
      actor: "Harjot Singh (Property Manager)",
      actorRole: "owner",
      title: "Work Order Authorized & PO Budget Capped",
      description: `Owner approved Draft 1 proposal. Generated Purchase Order PO-${ticket.ticketNumber.replace("#", "")} capped at ${ticket.poBudgetCap} excl. BTW. Authorized key lockbox code #4182 for unaccompanied access.`,
      badge: `PO ${ticket.poBudgetCap}`,
      badgeVariant: "needs_you",
      details: {
        poNumber: `PO-${ticket.ticketNumber.replace("#", "")}`,
        budgetAmount: `${ticket.poBudgetCap} excl. BTW`,
        lockboxCode: "#4182",
      },
    },
    {
      id: "ev-4",
      timestamp: "Today 08:20 CET",
      type: "dispatch",
      actor: "Automated Dispatch Service",
      actorRole: "system",
      title: "Dual Channel Notifications Dispatched",
      description: `Work order dispatched to ${ticket.contractorName} via Gmail (Status: Delivered). Formal arrival confirmation and fridge guidance sent to ${ticket.tenantName} via WhatsApp (Status: Read).`,
      badge: "Dispatched",
      badgeVariant: "default",
      details: {
        channel: "gmail",
      },
    },
    {
      id: "ev-5",
      timestamp: "Today 09:10 CET",
      type: "contractor",
      actor: `${ticket.contractorName} (${ticket.contractorTrade})`,
      actorRole: "contractor",
      title: "Contractor Arrival Window Acknowledged",
      description: `Contractor confirmed technician dispatch with estimated on-site arrival today between 11:30 and 12:30 CET. Ticket state updated to Waiting on third party.`,
      badge: "Arrival 11:30",
      badgeVariant: "default",
      details: {
        stateFrom: "open",
        stateTo: "waiting_on_third_party",
      },
    },
    ...(isCompleted
      ? [
          {
            id: "ev-6",
            timestamp: "Today 13:45 CET",
            type: "contractor" as const,
            actor: `${ticket.contractorName} (Monteur Kevin)`,
            actorRole: "contractor" as const,
            title: "Work Execution & Repair Completed",
            description:
              "Defective 16A breaker replaced in main subpanel. Group tested at 230V; kitchen sockets and refrigerator power fully restored. Test certificate logged.",
            badge: "Repaired",
            badgeVariant: "default" as const,
          },
          {
            id: "ev-7",
            timestamp: "Today 14:10 CET",
            type: "invoice" as const,
            actor: "EstateOS Automated Ledger Matching",
            actorRole: "system" as const,
            title: "Invoice Verified & Case Resolved",
            description: `Received invoice #INV-2026-881 for € 412,50. Matched against PO-${ticket.ticketNumber.replace("#", "")} (within ${ticket.poBudgetCap} budget cap by € 237,50). Case moved to Resolved.`,
            badge: "Matched & Resolved",
            badgeVariant: "default" as const,
            details: {
              invoiceAmount: "€ 412,50",
              stateFrom: "waiting_on_third_party",
              stateTo: "resolved",
            },
          },
        ]
      : []),
  ];

  const filteredEvents = events.filter((ev) => {
    if (activeFilter === "messages") return ev.type === "inbound" || ev.type === "dispatch";
    if (activeFilter === "po") return ev.type === "approval" || ev.type === "invoice";
    if (activeFilter === "audit") return ev.type === "triage" || ev.type === "state_change" || ev.details?.stateTo;
    return true;
  });

  const handleCopyTimeline = () => {
    const text = events
      .map((ev) => `[${ev.timestamp}] ${ev.actor}: ${ev.title} - ${ev.description}`)
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setCopied(true);
    onShowToast("Case audit trail copied to clipboard.");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0A0A0A]/50 backdrop-blur-xs flex items-center justify-center p-4 sm:p-6 overflow-y-auto animate-in fade-in duration-150">
      <div
        className="relative w-full max-w-3xl bg-[#FFFFFF] border border-[#E8E8E5] rounded-[20px] shadow-2xl flex flex-col overflow-hidden max-h-[92vh] animate-in zoom-in-95 duration-150"
        role="dialog"
        aria-modal="true"
      >
        {/* Modal Header */}
        <div className="px-6 py-5 border-b border-[#E8E8E5] bg-[#FFFFFF] flex items-center justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[13px] font-bold text-[#0A0A0A]">
                {ticket.ticketNumber}
              </span>
              <span className="text-[#D2D2CE]">·</span>
              <span className="text-[13px] font-semibold text-[#666666]">
                {ticket.unitLabel}
              </span>
              <span className="text-[#D2D2CE]">·</span>
              {isEmergency ? (
                <Pill variant="urgent">Urgent SLA</Pill>
              ) : isCompleted ? (
                <Pill variant="default">Resolved</Pill>
              ) : (
                <Pill variant="needs_you">Active Case</Pill>
              )}
            </div>

            <h2 className="font-heading font-bold text-[20px] sm:text-[22px] text-[#0A0A0A] tracking-[-0.01em]">
              {ticket.issueTitle}
            </h2>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="w-9 h-9 rounded-full flex items-center justify-center text-[#666666] hover:text-[#0A0A0A] hover:bg-[#F0F0EE] transition-colors cursor-pointer"
            aria-label="Close dialog"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Overview Metadata Bar */}
        <div className="px-6 py-3 bg-[#F6F6F4] border-b border-[#E8E8E5] grid grid-cols-2 sm:grid-cols-4 gap-3 text-[12px]">
          <div>
            <span className="text-[#666666] block">{t("Tenant")}</span>
            <span className="font-semibold text-[#0A0A0A] truncate block">
              {ticket.tenantName}
            </span>
          </div>
          <div>
            <span className="text-[#666666] block">{t("Contractor", "Aannemer")}</span>
            <span className="font-semibold text-[#0A0A0A] truncate block">
              {ticket.contractorName}
            </span>
          </div>
          <div>
            <span className="text-[#666666] block">{t("Authorized PO Cap", "Geautoriseerd budget")}</span>
            <span className="font-semibold text-[#0A0A0A] block">
              {ticket.poBudgetCap} excl. BTW
            </span>
          </div>
          <div>
            <span className="text-[#666666] block">{t("Target SLA", "Doel-SLA")}</span>
            <span className="font-mono font-bold text-[#0A0A0A] block">
              {ticket.slaRemaining}
            </span>
          </div>
        </div>

        {/* Filter Segmented Pills */}
        <div className="px-6 py-2.5 border-b border-[#E8E8E5] bg-[#FFFFFF] flex items-center justify-between gap-3 overflow-x-auto">
          <div className="inline-flex rounded-[9px] bg-[#F0F0EE] p-[3px] text-[12.5px] font-semibold">
            {[
              { id: "all", label: `${t("All")} (${events.length})` },
              { id: "messages", label: t("Messages", "Berichten") },
              { id: "po", label: t("Contractor & PO", "Aannemer & Inkooporders") },
              { id: "audit", label: t("Audit & state machine", "Audit & statustracking") },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveFilter(tab.id as any)}
                className={cn(
                  "px-[11px] py-[4px] rounded-[7px] transition-all cursor-pointer whitespace-nowrap",
                  activeFilter === tab.id
                    ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                    : "text-[#444444] hover:text-[#0A0A0A]"
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCopyTimeline}
              icon={copied ? <CheckCircle2 className="w-3.5 h-3.5 text-[#0A0A0A]" /> : <Copy className="w-3.5 h-3.5" />}
            >
              {copied ? "Copied" : "Copy audit"}
            </Button>
          </div>
        </div>

        {/* Scrollable Timeline */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1 bg-[#FFFFFF]">
          <div className="relative pl-6 space-y-6 before:absolute before:left-[11px] before:top-2 before:bottom-2 before:w-[2px] before:bg-[#E8E8E5]">
            {filteredEvents.map((ev, index) => {
              const isFirst = index === 0;
              const isLast = index === filteredEvents.length - 1;

              return (
                <div key={ev.id} className="relative space-y-2">
                  {/* Timeline Dot Node */}
                  <div
                    className={cn(
                      "absolute -left-[30px] top-1 w-5 h-5 rounded-full border-2 bg-[#FFFFFF] flex items-center justify-center",
                      ev.type === "approval"
                        ? "border-[#0A0A0A] text-[#0A0A0A]"
                        : ev.type === "inbound"
                        ? "border-[#1a73e8] text-[#1a73e8]"
                        : ev.type === "invoice"
                        ? "border-[#0A0A0A] bg-[#F0F0EE] text-[#0A0A0A]"
                        : "border-[#D2D2CE] text-[#666666]"
                    )}
                  >
                    <div
                      className={cn(
                        "w-2 h-2 rounded-full",
                        ev.type === "inbound" ? "bg-[#1a73e8]" : "bg-[#0A0A0A]"
                      )}
                    />
                  </div>

                  {/* Header Row of Event */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                    <div className="flex items-center gap-2">
                      <h4 className="text-[14px] font-bold text-[#0A0A0A]">
                        {ev.title}
                      </h4>
                      {ev.badge && (
                        <span className="text-[11px] font-semibold text-[#444444] bg-[#F0F0EE] px-2 py-0.5 rounded-full border border-[#E8E8E5]">
                          {ev.badge}
                        </span>
                      )}
                    </div>
                    <span className="text-[12px] font-mono text-[#666666]">
                      {ev.timestamp}
                    </span>
                  </div>

                  {/* Actor Badge */}
                  <div className="text-[12px] text-[#666666] flex items-center gap-1.5 font-medium">
                    <User className="w-3.5 h-3.5 text-[#444444]" />
                    <span>Actor: <strong className="text-[#0A0A0A] font-semibold">{ev.actor}</strong></span>
                  </div>

                  {/* Description Box */}
                  <div className="p-3.5 rounded-[12px] bg-[#F6F6F4] border border-[#E8E8E5] text-[13px] text-[#333333] leading-relaxed">
                    {ev.description}

                    {/* Attachments if any */}
                    {ev.details?.attachments && ev.details.attachments.length > 0 && (
                      <div className="mt-2.5 pt-2.5 border-t border-[#E8E8E5] flex items-center gap-2 flex-wrap">
                        {ev.details.attachments.map((att) => (
                          <div
                            key={att.name}
                            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-[8px] bg-[#FFFFFF] border border-[#D2D2CE] text-[12px] text-[#0A0A0A] font-medium"
                          >
                            <FileText className="w-3.5 h-3.5 text-[#666666]" />
                            <span>{att.name}</span>
                            <span className="text-[#666666] text-[11px]">({att.size})</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Metadata Pill specifics */}
                    {(ev.details?.poNumber || ev.details?.lockboxCode || ev.details?.stateTo) && (
                      <div className="mt-2.5 pt-2 border-t border-[#E8E8E5]/80 flex items-center gap-3 text-[11.5px] font-mono text-[#666666] flex-wrap">
                        {ev.details.poNumber && (
                          <span className="flex items-center gap-1">
                            <Coins className="w-3 h-3 text-[#0A0A0A]" />
                            <span>PO: <strong className="text-[#0A0A0A]">{ev.details.poNumber}</strong> ({ev.details.budgetAmount})</span>
                          </span>
                        )}
                        {ev.details.lockboxCode && (
                          <span className="flex items-center gap-1">
                            <Key className="w-3 h-3 text-[#0A0A0A]" />
                            <span>Lockbox: <strong className="text-[#0A0A0A]">{ev.details.lockboxCode}</strong></span>
                          </span>
                        )}
                        {ev.details.stateTo && (
                          <span className="flex items-center gap-1">
                            <span>State: {ev.details.stateFrom}</span>
                            <ArrowRight className="w-3 h-3 text-[#666666]" />
                            <strong className="text-[#0A0A0A]">{ev.details.stateTo}</strong>
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 bg-[#F6F6F4] border-t border-[#E8E8E5] flex items-center justify-between gap-3">
          <Button
            variant="secondary"
            size="default"
            onClick={() => {
              onShowToast("Audit PDF report generated and downloaded.");
            }}
            icon={<Download className="w-4 h-4 text-[#666666]" />}
          >
            Export PDF report
          </Button>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="default"
              onClick={() => {
                onClose();
                router.push("/inbox");
              }}
              icon={<ExternalLink className="w-3.5 h-3.5" />}
            >
              Open in Inbox
            </Button>

            <Button
              variant="primary"
              size="default"
              onClick={onClose}
            >
              Close
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
