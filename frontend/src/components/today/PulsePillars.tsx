"use client";

import React from "react";
import { PulseMetrics } from "@/types/dashboard";
import { Card } from "@/components/ui/Card";

interface PulsePillarsProps {
  metrics: PulseMetrics;
  onFilterNeedsYou?: () => void;
  onViewMoney?: () => void;
  onViewProperties?: () => void;
}

export function PulsePillars({
  metrics,
  onFilterNeedsYou,
}: PulsePillarsProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
      {/* Card 1: Need you */}
      <Card
        onClick={onFilterNeedsYou}
        className="cursor-pointer hover:border-[#D2D2CE] transition-all flex flex-col justify-between"
      >
        <span className="text-[13px] font-medium text-[#444444]">Need you</span>
        <div className="my-2.5">
          <span className="font-heading font-bold text-[32px] sm:text-[36px] text-[#0A0A0A] tabular-nums tracking-tight leading-none">
            {metrics.needsYouCount}
          </span>
        </div>
        <span className="text-[12.5px] text-[#666666]">in the queue</span>
      </Card>

      {/* Card 2: Urgent */}
      <Card
        onClick={onFilterNeedsYou}
        className="cursor-pointer hover:border-[#D2D2CE] transition-all flex flex-col justify-between"
      >
        <span className="text-[13px] font-medium text-[#444444]">Urgent</span>
        <div className="my-2.5">
          <span className="font-heading font-bold text-[32px] sm:text-[36px] text-[#0A0A0A] tabular-nums tracking-tight leading-none">
            {metrics.emergencyCount}
          </span>
        </div>
        <span className="text-[12.5px] text-[#666666]">act today</span>
      </Card>

      {/* Card 3: Auto-handled this week */}
      <Card className="flex flex-col justify-between">
        <span className="text-[13px] font-medium text-[#444444]">
          Auto-handled this week
        </span>
        <div className="my-2.5">
          <span className="font-heading font-bold text-[32px] sm:text-[36px] text-[#0A0A0A] tabular-nums tracking-tight leading-none">
            {metrics.autonomousActionsWeek}
          </span>
        </div>
        <span className="text-[12.5px] text-[#666666]">
          Gmail 61 · WhatsApp 48 · Portal 19 · Bank 14
        </span>
      </Card>
    </div>
  );
}
