"use client";

import React from "react";
import { ArrowUpRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";

interface OccupancyCardProps {
  onViewUnits?: () => void;
}

export function OccupancyCard({ onViewUnits }: OccupancyCardProps) {
  const buildings = [
    { name: "Keizersgracht (42-46)", rate: 100, occupied: 42, total: 42 },
    { name: "Prinsengracht (118-124)", rate: 92.1, occupied: 35, total: 38 },
    { name: "Herengracht Historic", rate: 90.0, occupied: 27, total: 30 },
  ];

  return (
    <Card className="flex flex-col justify-between">
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-[15px] font-semibold text-[#0A0A0A]">
              Portfolio occupancy
            </h3>
            <span className="text-[12.5px] text-[#666666] mt-0.5 block">
              104 / 110 units leased
            </span>
          </div>

          <span className="text-[16px] font-semibold text-[#0A0A0A] tabular-nums">
            94.5%
          </span>
        </div>

        {/* Building-wise mini progress bars */}
        <div className="space-y-3.5 mt-4 text-xs">
          {buildings.map((b) => (
            <div key={b.name} className="space-y-1.5">
              <div className="flex items-center justify-between text-[#0A0A0A]">
                <span className="font-medium truncate">{b.name}</span>
                <span className="text-[#666666] tabular-nums text-xs">
                  {b.occupied}/{b.total} ({b.rate}%)
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-[#F0F0EE] overflow-hidden">
                <div
                  className="h-full bg-[#0A0A0A] rounded-full transition-all"
                  style={{ width: `${b.rate}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-3 mt-4 border-t border-[#E8E8E5] flex items-center justify-between text-xs">
        <span className="text-[#444444] text-[13px] flex items-center gap-2 font-normal">
          <span className="w-2 h-2 rounded-full bg-[#0A0A0A]" />
          <span>2 units listed on Funda</span>
        </span>

        <Button
          variant="ghost"
          size="sm"
          onClick={onViewUnits}
          className="text-[#0A0A0A] hover:text-[#444444] font-semibold h-8 px-2"
        >
          <span>View 110 units</span>
          <ArrowUpRight className="w-3.5 h-3.5 ml-1" />
        </Button>
      </div>
    </Card>
  );
}
