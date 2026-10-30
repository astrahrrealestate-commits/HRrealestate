"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface SegmentedControlOption<T extends string = string> {
  id: T;
  label: string;
  count?: number;
  icon?: React.ReactNode;
}

export interface SegmentedControlProps<T extends string = string> {
  options: SegmentedControlOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div
      className={cn(
        "inline-flex items-center bg-[#F0F0EE] p-[3px] rounded-[9px] select-none",
        className
      )}
    >
      {options.map((opt) => {
        const isActive = value === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            className={cn(
              "text-[13px] font-semibold px-[11px] py-[5px] rounded-[7px] transition-all cursor-pointer flex items-center gap-1.5 leading-none",
              isActive
                ? "bg-[#FFFFFF] text-[#0A0A0A] shadow-[0_1px_2px_rgba(15,24,40,0.14)]"
                : "text-[#444444] hover:text-[#0A0A0A]"
            )}
          >
            {opt.icon && <span className="flex-shrink-0 opacity-80">{opt.icon}</span>}
            <span>{opt.label}</span>
            {opt.count !== undefined && (
              <span className="font-medium text-[#666666] tabular-nums text-[12px]">
                ({opt.count})
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
