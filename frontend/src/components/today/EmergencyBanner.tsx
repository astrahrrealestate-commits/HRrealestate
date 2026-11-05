"use client";

import React from "react";
import { Clock, Wrench } from "lucide-react";
import { TriageItem } from "@/types/dashboard";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";

interface EmergencyBannerProps {
  emergencyItem?: TriageItem;
  onSelectEmergency?: (item: TriageItem) => void;
}

export function EmergencyBanner({
  emergencyItem,
  onSelectEmergency,
}: EmergencyBannerProps) {
  if (!emergencyItem) return null;

  return (
    <div className="mb-6 rounded-[18px] border border-[#1a73e8] bg-white p-4 transition-all">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Left Side: Critical Badge & Details */}
        <div className="flex items-start gap-3">
          <Pill variant="urgent" className="mt-0.5">
            Emergency
          </Pill>
          <div className="space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-semibold text-[#0A0A0A]">
                {emergencyItem.unitLabel} · {emergencyItem.senderName}
              </span>
              <span className="text-xs font-mono text-[#666666] flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" />
                <span>{emergencyItem.slaRemainingMinutes ?? 42}m SLA</span>
              </span>
            </div>
            <p className="text-xs text-[#444444] leading-relaxed">
              {emergencyItem.parsedSummary}
            </p>
          </div>
        </div>

        {/* Right Side: Quick Action Button */}
        <Button
          variant="primary"
          size="default"
          onClick={() => onSelectEmergency?.(emergencyItem)}
          icon={<Wrench className="w-3.5 h-3.5" />}
        >
          Review emergency
        </Button>
      </div>
    </div>
  );
}
