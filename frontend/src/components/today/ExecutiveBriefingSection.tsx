"use client";

import React, { useState } from "react";
import {
  Sun,
  BarChart2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { ExecutiveBriefing, BriefingKind } from "@/types/dashboard";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { cn } from "@/lib/utils";

interface ExecutiveBriefingSectionProps {
  dailyBriefing: ExecutiveBriefing;
  weeklySummary: ExecutiveBriefing;
}

export function ExecutiveBriefingSection({
  dailyBriefing,
  weeklySummary,
}: ExecutiveBriefingSectionProps) {
  const [activeKind, setActiveKind] = useState<BriefingKind>("daily");
  const [isExpanded, setIsExpanded] = useState<boolean>(false);

  const activeData = activeKind === "daily" ? dailyBriefing : weeklySummary;

  return (
    <div className="space-y-3.5">
      {/* Top Bar: Date, Toggle Switcher (Daily vs Weekly), and Heading */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <span className="text-[12px] font-semibold text-[#666666] uppercase tracking-[0.06em] block mb-1">
            {activeData.dayLabel} · Delivered {activeData.timeDelivered}
          </span>
          <h1 className="font-heading font-bold text-[28px] sm:text-[32px] tracking-[-0.02em] text-[#0A0A0A] leading-tight">
            {activeKind === "daily" ? "Good morning, Harjot" : "Weekly executive review, Harjot"}
          </h1>
        </div>

        {/* Daily vs Weekly Segmented Switcher */}
        <div className="inline-flex rounded-[9px] bg-[#F0F0EE] p-[3px] self-start sm:self-auto text-[13px] font-semibold">
          <button
            onClick={() => {
              setActiveKind("daily");
              setIsExpanded(false);
            }}
            className={cn(
              "px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer flex items-center gap-1.5",
              activeKind === "daily"
                ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            <Sun className="w-3.5 h-3.5 text-[#444444]" />
            <span>Daily pulse</span>
          </button>

          <button
            onClick={() => {
              setActiveKind("weekly");
              setIsExpanded(false);
            }}
            className={cn(
              "px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer flex items-center gap-1.5",
              activeKind === "weekly"
                ? "bg-white text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            <BarChart2 className="w-3.5 h-3.5 text-[#444444]" />
            <span>Weekly recap</span>
          </button>
        </div>
      </div>

      {/* Main AI Summary Sentence (with Spark ✦) */}
      <div className="flex items-start justify-between gap-4 max-w-4xl">
        <p className="text-[14px] text-[#444444] leading-relaxed flex items-start gap-2">
          <span className="text-[#F25C05] text-[15px] leading-none mt-0.5 flex-shrink-0 font-bold">
            ✦
          </span>
          <span>
            {activeKind === "daily" ? (
              <>
                Since yesterday evening I read 22 messages and filed or answered 17.{" "}
                <strong className="font-semibold text-[#0A0A0A]">
                  Five need your call, one is urgent.
                </strong>{" "}
                A rent reminder run is ready too.
              </>
            ) : (
              <>
                {weeklySummary.summarySentence}{" "}
                <strong className="font-semibold text-[#0A0A0A]">
                  142 autonomous entries logged this week.
                </strong>
              </>
            )}
          </span>
        </p>

        {/* Toggle Expand Details */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="text-[#666666] hover:text-[#0A0A0A] font-medium h-8 px-2 flex-shrink-0"
        >
          <span>{isExpanded ? "Hide breakdown" : "View breakdown"}</span>
          {isExpanded ? (
            <ChevronUp className="w-3.5 h-3.5 ml-1" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 ml-1" />
          )}
        </Button>
      </div>

      {/* Expanded Breakdown Accordion */}
      {isExpanded && (
        <Card className="animate-in fade-in slide-in-from-top-1 duration-200 p-5 sm:p-6 space-y-5 bg-[#FFFFFF] border border-[#E8E8E5] rounded-[18px] shadow-sm">
          {/* Card Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-[#E8E8E5]">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-[8px] bg-[#FFF1E7] border border-[#F7C3A0] flex items-center justify-center text-[#F25C05] text-[13px] font-bold">
                ✦
              </div>
              <div>
                <h3 className="font-heading font-bold text-[15px] text-[#0A0A0A] tracking-[-0.01em]">
                  {activeKind === "daily"
                    ? "Morning Executive Briefing & Triage Breakdown"
                    : "Weekly Portfolio Operations & Audit Breakdown"}
                </h3>
                <p className="text-[12px] text-[#666666]">
                  {activeKind === "daily"
                    ? "Generated at 07:30 CET from Gmail, WhatsApp, and ING Bank feed"
                    : "Consolidated portfolio audit delivered Friday 16:00 CET"}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 self-start sm:self-auto">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[6px] bg-[#F0F0EE] border border-[#E8E8E5] text-[11.5px] font-mono text-[#555555]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#1B5E20]" />
                {activeKind === "daily" ? "07:30 Digest Active" : "Weekly Audit Verified"}
              </span>
            </div>
          </div>

          {/* Section Columns Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
            {activeData.sections.map((section, idx) => {
              const isUrgentSection = section.title.toLowerCase().includes("urgent");

              return (
                <div key={idx} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] font-semibold text-[#666666] uppercase tracking-[0.06em] flex items-center gap-2">
                      <span>{section.title}</span>
                      <span className="text-[11px] font-mono font-normal text-[#888888] bg-[#F0F0EE] px-1.5 py-0.2 rounded">
                        {section.items.length}
                      </span>
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {section.items.map((item, itemIdx) => {
                      const isUrgentItem =
                        isUrgentSection ||
                        item.badge?.toLowerCase().includes("urgent") ||
                        item.badge?.toLowerCase().includes("emergency");

                      return (
                        <div
                          key={item.id || itemIdx}
                          className={cn(
                            "rounded-[14px] p-4 text-[13px] transition-all border shadow-2xs",
                            isUrgentItem
                              ? "bg-[#FFFFFF] border-[#F7C3A0] border-l-[4px] border-l-[#F25C05]"
                              : "bg-[#FFFFFF] border-[#E8E8E5] hover:border-[#D2D2CE]"
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="space-y-1 min-w-0">
                              <span className="font-semibold text-[#0A0A0A] leading-snug block text-[13.5px]">
                                {item.title}
                              </span>
                              {item.detail && (
                                <p className="text-[#555555] leading-relaxed text-[12.5px]">
                                  {item.detail}
                                </p>
                              )}
                            </div>

                            <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
                              {item.badge && (
                                <Pill
                                  variant={isUrgentItem ? "urgent" : "needs_you"}
                                >
                                  {item.badge}
                                </Pill>
                              )}
                              {item.time && (
                                <span className="text-[11px] font-mono text-[#888888]">
                                  {item.time}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Footer Metrics Banner */}
          <div className="pt-3.5 border-t border-[#E8E8E5] flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 text-[12px] text-[#666666]">
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 bg-[#E1F1E5] text-[#1B5E20] border border-[#86BE97] px-2 py-0.5 rounded-full font-semibold text-[11px]">
                ✓ Zero SLA breaches
              </span>
              <span>
                Auto-triage filtered {activeData.ignoredCount || 18} routine receipts & newsletters
              </span>
            </div>
            <span className="font-mono text-[11px] text-[#888888]">
              EstateOS Autonomous Triage Engine v2.4
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}
