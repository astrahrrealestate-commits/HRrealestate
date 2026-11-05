"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  User,
  Wrench,
} from "lucide-react";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

export interface EmergencyItem {
  id: string;
  rank: number;
  ticketNumber: string;
  unitLabel: string;
  issueTitle: string;
  slaFormatted: string;
  tenantName: string;
  tenantContact: string;
  tenantReportedText: string;
  tenantDraftSnippet: string;
  contractorName: string;
  contractorTrade: string;
  contractorContact: string;
  budgetCap: string;
  lockboxCode: string;
  contractorDraftSnippet: string;
  tenantThreadId: string;
  contractorThreadId: string;
}

export const TOP_3_EMERGENCIES: EmergencyItem[] = [
  {
    id: "em-1",
    rank: 1,
    ticketNumber: "#005",
    unitLabel: "Pieter Floriszstraat 1 C",
    issueTitle: "Kitchen sockets short circuit · Fridge warming up",
    slaFormatted: "38m SLA",
    tenantName: "Pieter Bakker",
    tenantContact: "+31 6 12 34 41 87",
    tenantReportedText: "Still no power in kitchen sockets since short circuit. Fridge is warm. Can someone come today?",
    tenantDraftSnippet: "Monteur Kevin van Chahal Bouw arriveert vandaag om 11:30. Hou koelkast dicht.",
    contractorName: "Chahal Bouw Electricians",
    contractorTrade: "Electrician",
    contractorContact: "+31 6 55 55 98 12",
    budgetCap: "€ 650,- excl BTW",
    lockboxCode: "4182",
    contractorDraftSnippet: "Spoeddispatch ticket #005 geaccordeerd 11:30. Budget: € 650,-. Sleutelkluis: 4182.",
    tenantThreadId: "thread-1",
    contractorThreadId: "thread-2",
  },
  {
    id: "em-2",
    rank: 2,
    ticketNumber: "#010",
    unitLabel: "Dorpsstraat 54 E",
    issueTitle: "Washing machine siphon burst · Leaking water into closet",
    slaFormatted: "1h 14m SLA",
    tenantName: "Rick de Boer",
    tenantContact: "+31 6 22 41 89 00",
    tenantReportedText: "Wasmachine lekt water sinds gisteravond. Uitgezet. Vanaf 17:00 thuis voor monteur.",
    tenantDraftSnippet: "Ticket #010 aangemaakt voor Chahal Bouw. Loodgieter neemt contact op voor na 17:00.",
    contractorName: "Chahal Bouw / Vermeer Loodgieters",
    contractorTrade: "Plumber",
    contractorContact: "+31 6 55 55 98 12",
    budgetCap: "€ 450,- excl BTW",
    lockboxCode: "Tenant home after 17:00",
    contractorDraftSnippet: "Spoedopdracht ticket #010 Dorpsstraat 54 E: lekkage afvoer. Budget: € 450,-.",
    tenantThreadId: "thread-3",
    contractorThreadId: "thread-2",
  },
  {
    id: "em-3",
    rank: 3,
    ticketNumber: "#014",
    unitLabel: "Singel 412",
    issueTitle: "Central heating boiler error F.22 · Pressure 0.4 bar, no heat",
    slaFormatted: "1h 45m SLA",
    tenantName: "Marloes Jansen",
    tenantContact: "+31 6 44 22 88 19",
    tenantReportedText: "Geen verwarming meer op Singel 412. Storingscode F.22, druk 0.4 bar. Koud in huis.",
    tenantDraftSnippet: "Melding #014 met spoed doorgegeven aan Van Dijk CV. Monteur komt morgen 09:00.",
    contractorName: "Van Dijk CV & Verwarming",
    contractorTrade: "Heating Engineer",
    contractorContact: "+31 6 88 12 34 56",
    budgetCap: "€ 550,- excl BTW",
    lockboxCode: "Tenant present",
    contractorDraftSnippet: "Werkorder #014 Singel 412 radiator & drukherstel geaccordeerd voor 09:00.",
    tenantThreadId: "thread-8",
    contractorThreadId: "thread-7",
  },
];

interface EmergencyDeckProps {
  onDispatchTenant?: (emergencyId: string) => void;
  onDispatchContractor?: (emergencyId: string) => void;
  onDispatchBoth?: (emergencyId: string) => void;
}

export function EmergencyDeck({
  onDispatchTenant,
  onDispatchContractor,
  onDispatchBoth,
}: EmergencyDeckProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [expandedEmergencyId, setExpandedEmergencyId] = useState<string>("em-1");
  const [dispatchedMap, setDispatchedMap] = useState<Record<string, boolean>>({});

  const topEmergency = TOP_3_EMERGENCIES[0];

  const handleRedirectToTenant = (threadId: string) => {
    router.push(`/inbox?audience=tenants&thread=${threadId}`);
  };

  const handleRedirectToContractor = (threadId: string) => {
    router.push(`/inbox?audience=contractors&category=contractor_repairs&thread=${threadId}`);
  };

  const handleQuickApproveBoth = (em: EmergencyItem) => {
    setDispatchedMap((prev) => ({ ...prev, [em.id]: true }));
    onDispatchBoth?.(em.id);
  };

  return (
    <div className="rounded-[18px] border border-[#1a73e8] bg-white transition-all overflow-hidden">
      {/* 1. Single-Row Minimal Emergency Banner */}
      <div className="p-3.5 sm:px-5 sm:py-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        {/* Left: Orange pill + One-line summary */}
        <div className="flex items-center gap-3 min-w-0">
          <Pill variant="urgent" className="flex-shrink-0">
            Emergency
          </Pill>

          <div className="flex items-center gap-2 truncate text-sm">
            <span className="font-semibold text-[#0A0A0A] truncate">
              {topEmergency.unitLabel}:
            </span>
            <span className="text-[#444444] truncate hidden md:inline">
              {topEmergency.issueTitle}
            </span>
            <span className="text-xs font-mono text-[#666666] px-2 py-0.5 rounded-full bg-[#F0F0EE] flex-shrink-0">
              {topEmergency.slaFormatted}
            </span>
          </div>
        </div>

        {/* Right: Neutral Buttons */}
        <div className="flex items-center gap-2 flex-shrink-0 self-end sm:self-center">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleRedirectToTenant(topEmergency.tenantThreadId)}
            icon={<User className="w-3.5 h-3.5 text-[#444444]" />}
          >
            Reply to tenant
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleRedirectToContractor(topEmergency.contractorThreadId)}
            icon={<Wrench className="w-3.5 h-3.5 text-[#444444]" />}
          >
            Connect contractor
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsOpen((prev) => !prev)}
            className="text-[#444444] hover:text-[#0A0A0A]"
          >
            <span>Top 3</span>
            {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </div>

      {/* 2. Dropdown Accordion */}
      {isOpen && (
        <div className="border-t border-[#E8E8E5] bg-white p-4 sm:p-5 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-[#E8E8E5] text-xs text-[#666666]">
            <span className="font-semibold uppercase tracking-[0.06em]">Active emergency tickets</span>
            <span>Click to review details and redirect to inbox</span>
          </div>

          <div className="space-y-2">
            {TOP_3_EMERGENCIES.map((em) => {
              const isExpanded = expandedEmergencyId === em.id;
              const isDispatched = dispatchedMap[em.id];

              return (
                <div
                  key={em.id}
                  className={cn(
                    "rounded-[12px] border transition-all",
                    isExpanded
                      ? "bg-[#F0F0EE] border-[#D2D2CE]"
                      : "bg-white border-[#E8E8E5] hover:border-[#D2D2CE]"
                  )}
                >
                  {/* Header Row */}
                  <div
                    onClick={() => setExpandedEmergencyId(isExpanded ? "" : em.id)}
                    className="p-3 flex items-center justify-between gap-3 cursor-pointer"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span className="text-xs font-semibold text-[#666666] w-5">
                        #{em.rank}
                      </span>
                      <span className="font-semibold text-xs text-[#0A0A0A] truncate">
                        {em.unitLabel}
                      </span>
                      <span className="text-xs text-[#D2D2CE]">·</span>
                      <span className="text-xs text-[#444444] truncate font-normal">
                        {em.issueTitle}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0">
                      <Pill variant="urgent">
                        {em.slaFormatted}
                      </Pill>
                      {isExpanded ? (
                        <ChevronUp className="w-4 h-4 text-[#666666]" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-[#666666]" />
                      )}
                    </div>
                  </div>

                  {/* Expanded Content */}
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-1 border-t border-[#E8E8E5] space-y-3 text-xs">
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
                        {/* Tenant Report */}
                        <div className="bg-white p-3 rounded-[12px] border border-[#E8E8E5] space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-[#0A0A0A] flex items-center gap-1.5">
                              <User className="w-3.5 h-3.5 text-[#444444]" />
                              <span>Reporting tenant: {em.tenantName}</span>
                            </span>
                            <span className="text-[#666666]">{em.tenantContact}</span>
                          </div>
                          {/* Plain quote in sunken box */}
                          <div className="rounded-[12px] bg-[#F0F0EE] p-[14px_16px] text-xs text-[#444444] italic leading-relaxed">
                            "{em.tenantReportedText}"
                          </div>
                          <div className="text-[#444444] text-xs">
                            <span className="font-medium text-[#0A0A0A]">Draft reply:</span> "{em.tenantDraftSnippet}"
                          </div>
                        </div>

                        {/* Responsible Contractor */}
                        <div className="bg-white p-3 rounded-[12px] border border-[#E8E8E5] space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="font-medium text-[#0A0A0A] flex items-center gap-1.5">
                              <Wrench className="w-3.5 h-3.5 text-[#444444]" />
                              <span>Contractor: {em.contractorName}</span>
                            </span>
                            <Pill variant="default">{em.contractorTrade}</Pill>
                          </div>
                          <div className="text-xs text-[#444444] flex items-center justify-between bg-[#F0F0EE] p-2.5 rounded-[8px] border border-[#E8E8E5]">
                            <span>PO budget cap: <strong className="text-[#0A0A0A]">{em.budgetCap}</strong></span>
                            <span>Lockbox: <strong className="text-[#0A0A0A]">{em.lockboxCode}</strong></span>
                          </div>
                          <div className="text-[#444444] text-xs">
                            <span className="font-medium text-[#0A0A0A]">Dispatch draft:</span> "{em.contractorDraftSnippet}"
                          </div>
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between pt-2 gap-2 border-t border-[#E8E8E5]">
                        <div className="flex items-center gap-2">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleRedirectToTenant(em.tenantThreadId)}
                            icon={<User className="w-3.5 h-3.5 text-[#444444]" />}
                          >
                            Reply to {em.tenantName.split(" ")[0]}
                          </Button>

                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => handleRedirectToContractor(em.contractorThreadId)}
                            icon={<Wrench className="w-3.5 h-3.5 text-[#444444]" />}
                          >
                            Connect {em.contractorName.split(" ")[0]}
                          </Button>
                        </div>

                        <Button
                          variant={isDispatched ? "secondary" : "primary"}
                          size="sm"
                          onClick={() => handleQuickApproveBoth(em)}
                          disabled={isDispatched}
                        >
                          {isDispatched ? (
                            <>
                              <CheckCircle2 className="w-3.5 h-3.5 text-[#0A0A0A]" />
                              <span>Dispatched</span>
                            </>
                          ) : (
                            <span>1-click approve both</span>
                          )}
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
