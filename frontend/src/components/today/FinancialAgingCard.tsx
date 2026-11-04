"use client";

import React from "react";
import { ArrowUpRight } from "lucide-react";
import { formatCurrency } from "@/lib/utils";
import { Card } from "@/components/ui/Card";
import { Pill } from "@/components/ui/Pill";
import { Button } from "@/components/ui/Button";

interface FinancialAgingCardProps {
  totalAmount?: number;
  onReviewReminders?: () => void;
}

export function FinancialAgingCard({
  totalAmount = 165734.99,
  onReviewReminders,
}: FinancialAgingCardProps) {
  const buckets = [
    {
      label: "0–30 days",
      amount: 120400.0,
      percentage: 72.6,
      barColor: "bg-[#0A0A0A]",
      dotColor: "bg-[#0A0A0A]",
      description: "Current cycle receivables",
    },
    {
      label: "30–90 days",
      amount: 35334.99,
      percentage: 21.3,
      barColor: "bg-[#666666]",
      dotColor: "bg-[#666666]",
      description: "3 reminder drafts ready",
    },
    {
      label: "90+ days",
      amount: 10000.0,
      percentage: 6.1,
      barColor: "bg-[#1a73e8]",
      dotColor: "bg-[#1a73e8]",
      description: "Formal legal review zone",
    },
  ];

  return (
    <Card className="flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-[15px] font-semibold text-[#0A0A0A]">
              Open rent & aging
            </h3>
            <span className="text-[12.5px] text-[#666666] mt-0.5 block">
              Receivables distribution
            </span>
          </div>

          <span className="text-[16px] font-semibold text-[#0A0A0A] tabular-nums">
            {formatCurrency(totalAmount)}
          </span>
        </div>

        {/* Multi-segment stacked progress bar */}
        <div className="h-2 w-full rounded-full bg-[#F0F0EE] overflow-hidden flex gap-0.5 my-4">
          {buckets.map((b) => (
            <div
              key={b.label}
              style={{ width: `${b.percentage}%` }}
              className={`${b.barColor} h-full transition-all`}
              title={`${b.label}: ${formatCurrency(b.amount)} (${b.percentage}%)`}
            />
          ))}
        </div>

        {/* Bucket breakdown details */}
        <div className="space-y-2 mt-4 text-xs">
          {buckets.map((b) => (
            <div key={b.label} className="flex items-center justify-between py-1.5 border-b border-[#E8E8E5] last:border-b-0">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${b.dotColor}`} />
                <span className="text-[#0A0A0A] font-medium">{b.label}</span>
                <span className="text-[#666666] hidden sm:inline">
                  ({b.description})
                </span>
              </div>
              <span className="font-semibold text-[#0A0A0A] tabular-nums">
                {formatCurrency(b.amount)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-3 mt-4 border-t border-[#E8E8E5] flex items-center justify-between">
        <Pill variant="urgent">
          3 overdue notices
        </Pill>

        <Button
          variant="ghost"
          size="sm"
          onClick={onReviewReminders}
          className="text-[#0A0A0A] hover:text-[#444444] font-semibold h-8 px-2"
        >
          <span>Review reminders</span>
          <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>
    </Card>
  );
}
