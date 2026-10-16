"use client";

import React, { useState } from "react";
import {
  CheckCircle2,
} from "lucide-react";
import { cn, formatCurrency } from "@/lib/utils";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export interface StalledItem {
  id: string;
  type: "unpaid_rent" | "contractor_stalled" | "moveout_pending";
  unitLabel: string;
  partyName: string;
  partyRole: string;
  contact: string;
  subject: string;
  amount?: number;
  remindersSentCount: number;
  lastMessageSent: string;
  daysStalled: number;
  statusBadge: string;
  proposedActionLabel: string;
  proposedActionDraft: string;
}

export const INITIAL_STALLED_ITEMS: StalledItem[] = [
  {
    id: "stall-1",
    type: "contractor_stalled",
    unitLabel: "Singel 412",
    partyName: "FastFix Loodgieters",
    partyRole: "Contractor · Heating & Plumbing",
    contact: "+31 20 555 0199",
    subject: "Radiator valve quote · Dispatched 3 days ago",
    remindersSentCount: 1,
    lastMessageSent: "3 days ago via Email",
    daysStalled: 3,
    statusBadge: "Awaiting quote response",
    proposedActionLabel: "Send nudge",
    proposedActionDraft:
      "Beste FastFix, heeft u al gelegenheid gehad om naar de offerte voor de radiatorkranen op Singel 412 te kijken? We horen het graag. Groet, H R Real Estate.",
  },
  {
    id: "stall-2",
    type: "unpaid_rent",
    unitLabel: "Keizersgracht 42-A",
    partyName: "Anouk de Jong",
    partyRole: "Tenant",
    contact: "+31 6 49 18 27 36",
    subject: "October rent overdue · 14-day statutory threshold",
    amount: 2150.0,
    remindersSentCount: 2,
    lastMessageSent: "3 days ago via WhatsApp",
    daysStalled: 11,
    statusBadge: "2 reminders sent",
    proposedActionLabel: "Send demand notice",
    proposedActionDraft:
      "Beste Anouk, ondanks eerdere herinneringen staat de huur van € 2.150,- voor Keizersgracht 42-A nog open. Gelieve binnen 5 werkdagen te voldoen om verdere incassomaatregelen te voorkomen. Groet, H R Real Estate.",
  },
  {
    id: "stall-3",
    type: "unpaid_rent",
    unitLabel: "Prinsengracht 118 B",
    partyName: "Daan Vermeulen",
    partyRole: "Tenant",
    contact: "daan.vermeulen@gmail.com",
    subject: "October rent overdue · Email reminder unread",
    amount: 1890.0,
    remindersSentCount: 1,
    lastMessageSent: "4 days ago via Email",
    daysStalled: 9,
    statusBadge: "Email unopened",
    proposedActionLabel: "Send reminder",
    proposedActionDraft:
      "Hoi Daan, we zagen dat de huur van € 1.890,- voor Prinsengracht 118 B nog openstaat. Lukt het om dit vandaag via iDEAL over te maken? Groet, H R Real Estate.",
  },
  {
    id: "stall-4",
    type: "moveout_pending",
    unitLabel: "Henry Dunantweg 5 F",
    partyName: "Lars van den Berg",
    partyRole: "Tenant",
    contact: "lars@vandenberg.nl",
    subject: "Pre-inspection booking link pending · 5 days without response",
    remindersSentCount: 1,
    lastMessageSent: "5 days ago via Email",
    daysStalled: 5,
    statusBadge: "Handover pending",
    proposedActionLabel: "Resend link",
    proposedActionDraft:
      "Beste Lars, ter herinnering voor je opzegging per 31 december: gelieve via deze link de voorinspectie in te plannen voor de sleuteloverdracht. Groet, H R Real Estate.",
  },
];

interface UnresponsiveRadarCardProps {
  items?: StalledItem[];
  onActionTriggered?: (item: StalledItem) => void;
}

export function UnresponsiveRadarCard({ items: propItems, onActionTriggered }: UnresponsiveRadarCardProps) {
  const items = propItems && propItems.length > 0 ? propItems : INITIAL_STALLED_ITEMS;
  const [filterType, setFilterType] = useState<"all" | "unpaid_rent" | "contractor_stalled">("all");
  const [resolvedIds, setResolvedIds] = useState<Record<string, boolean>>({});

  const filteredItems = items.filter((item) => {
    if (filterType === "all") return true;
    return item.type === filterType;
  });

  const handleResolveAction = (item: StalledItem) => {
    setResolvedIds((prev) => ({ ...prev, [item.id]: true }));
    onActionTriggered?.(item);
  };

  return (
    <Card className="space-y-4">
      {/* 1. Header with Title and Segment Filter */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#E8E8E5]">
        <div>
          <div className="flex items-center gap-2.5">
            <h3 className="text-[16px] font-semibold text-[#0A0A0A] leading-tight">
              Unresponsive cases
            </h3>
            <Pill variant="default">
              {items.length} awaiting response
            </Pill>
          </div>
          <p className="text-[12.5px] text-[#666666] mt-1">
            Tenants with unpaid rent and contractors with unconfirmed work orders where reminders were sent.
          </p>
        </div>

        {/* Filter Segment */}
        <div className="inline-flex rounded-[9px] bg-[#F0F0EE] p-[3px] text-[13px] font-semibold self-start sm:self-auto">
          <button
            onClick={() => setFilterType("all")}
            className={cn(
              "px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer",
              filterType === "all"
                ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            All ({items.length})
          </button>
          <button
            onClick={() => setFilterType("unpaid_rent")}
            className={cn(
              "px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer",
              filterType === "unpaid_rent"
                ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            Unpaid rent
          </button>
          <button
            onClick={() => setFilterType("contractor_stalled")}
            className={cn(
              "px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer",
              filterType === "contractor_stalled"
                ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            Contractors
          </button>
        </div>
      </div>

      {/* 2. Stalled Items List */}
      <div className="space-y-3">
        {filteredItems.map((item) => {
          const isResolved = resolvedIds[item.id];
          const isRent = item.type === "unpaid_rent";

          return (
            <div
              key={item.id}
              className={cn(
                "p-4 rounded-[12px] border border-[#E8E8E5] transition-all flex flex-col md:flex-row md:items-center justify-between gap-3 bg-white hover:border-[#D2D2CE]",
                isResolved && "opacity-50 bg-[#F0F0EE]/60"
              )}
            >
              {/* Left Detail Block */}
              <div className="space-y-1.5 flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Pill variant="default">
                    {isRent ? "Unpaid rent" : "Work order"}
                  </Pill>

                  <span className="text-[13px] font-semibold text-[#0A0A0A]">{item.unitLabel}</span>
                  <span className="text-xs text-[#D2D2CE]">·</span>
                  <span className="text-[12.5px] text-[#666666]">
                    {item.partyName} ({item.contact})
                  </span>

                  {item.amount && (
                    <span className="text-xs font-semibold text-[#0A0A0A] tabular-nums ml-auto md:ml-0 bg-[#F0F0EE] px-2 py-0.5 rounded-[6px] border border-[#E8E8E5]">
                      {formatCurrency(item.amount)}
                    </span>
                  )}
                </div>

                <p className="text-[13px] text-[#444444] leading-snug">
                  {item.subject}
                </p>

                {/* Status & Tracker */}
                <div className="flex items-center gap-3 text-[12.5px] text-[#666666] flex-wrap">
                  <span>
                    {item.remindersSentCount} {item.remindersSentCount === 1 ? "reminder" : "reminders"} sent
                  </span>
                  <span>·</span>
                  <span>Last touch: {item.lastMessageSent}</span>
                  <span>·</span>
                  <Pill variant={item.daysStalled >= 7 ? "urgent" : "needs_you"}>
                    {item.daysStalled} {item.daysStalled === 1 ? "day" : "days"} open
                  </Pill>
                </div>
              </div>

              {/* Right Action Block */}
              <div className="flex items-center gap-2 flex-shrink-0 self-end md:self-center">
                <Button
                  variant={isResolved ? "secondary" : "primary"}
                  size="default"
                  onClick={() => handleResolveAction(item)}
                  disabled={isResolved}
                >
                  {isResolved ? (
                    <>
                      <CheckCircle2 className="w-4 h-4 text-[#0A0A0A]" />
                      <span>Action sent</span>
                    </>
                  ) : (
                    <span>{item.proposedActionLabel}</span>
                  )}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
