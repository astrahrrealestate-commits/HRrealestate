"use client";

import React from "react";
import { ArrowUpRight, CheckCircle2 } from "lucide-react";
import { AutonomousActionLog } from "@/types/dashboard";
import { Card } from "@/components/ui/Card";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";

interface AutonomousLogCardProps {
  logs: AutonomousActionLog[];
  onViewAuditTrail?: () => void;
}

export function AutonomousLogCard({
  logs,
  onViewAuditTrail,
}: AutonomousLogCardProps) {
  return (
    <Card className="flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-[#1a73e8] text-[15px] leading-none font-bold">✦</span>
            <div>
              <h3 className="text-[15px] font-semibold text-[#0A0A0A] leading-none">
                Auto-handled this week
              </h3>
              <span className="text-[12.5px] text-[#666666] mt-1 block">
                Autonomous background actions
              </span>
            </div>
          </div>

          <Pill variant="default">
            142 this week
          </Pill>
        </div>

        {/* Audit stream items */}
        <div className="space-y-3 mt-4">
          {logs.slice(0, 3).map((log) => (
            <div key={log.id} className="flex items-start gap-2.5 text-xs">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#0A0A0A] mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-[#444444] font-normal leading-snug line-clamp-2 text-[12.5px]">
                  {log.actionText}
                </p>
                <div className="flex items-center gap-2 mt-1 text-[#666666] text-[12px]">
                  <span className="font-mono">{log.timestamp}</span>
                  <span>·</span>
                  <span>{log.tag}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-3 mt-4 border-t border-[#E8E8E5] flex items-center justify-between text-xs">
        <span className="text-[#666666]">
          Saved ~8.5 hours
        </span>

        <Button
          variant="ghost"
          size="sm"
          onClick={onViewAuditTrail}
          className="text-[#0A0A0A] hover:text-[#444444] font-semibold h-8 px-2"
        >
          <span>Full audit log</span>
          <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>
    </Card>
  );
}
