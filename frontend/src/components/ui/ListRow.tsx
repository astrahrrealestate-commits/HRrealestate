"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface ListRowProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.ReactNode;
  title: string;
  subtitle?: React.ReactNode;
  meta?: React.ReactNode;
  actionLine?: React.ReactNode;
  actionIcon?: React.ReactNode;
  time?: string;
  statusPill?: React.ReactNode;
  isSelected?: boolean;
}

export function ListRow({
  icon,
  title,
  subtitle,
  meta,
  actionLine,
  actionIcon,
  time,
  statusPill,
  isSelected = false,
  className,
  ...props
}: ListRowProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-[36px_1fr_auto] gap-[12px] p-[14px_16px] min-h-[44px] cursor-pointer transition-colors border-t border-[#E8E8E5] first:border-t-0 select-none",
        isSelected
          ? "bg-[#eff6ff]"
          : "bg-transparent hover:bg-[#F0F0EE]",
        className
      )}
      {...props}
    >
      {/* Left: 36px circle */}
      <div
        className={cn(
          "w-9 h-9 rounded-full flex items-center justify-center transition-colors flex-shrink-0 mt-0.5",
          isSelected
            ? "bg-[#1a73e8] text-[#0A0A0A]"
            : "bg-[#F0F0EE] text-[#444444]"
        )}
      >
        {icon}
      </div>

      {/* Middle: Title, Subtitle / Sender, Meta, Action */}
      <div className="flex flex-col gap-[2px] min-w-0 justify-center">
        <span className="text-[14px] font-semibold text-[#0A0A0A] truncate leading-tight">
          {title}
        </span>

        {(subtitle || meta) && (
          <div className="flex items-center gap-1.5 text-[12.5px] text-[#666666] truncate">
            {subtitle && <span className="truncate">{subtitle}</span>}
            {subtitle && meta && <span className="opacity-50">·</span>}
            {meta && <span className="truncate">{meta}</span>}
          </div>
        )}

        {actionLine && (
          <div className="flex items-center gap-1.5 text-[13px] text-[#444444] mt-0.5 truncate">
            {actionIcon ? (
              <span className="text-[#1557b0] flex-shrink-0">{actionIcon}</span>
            ) : (
              <span className="text-[#1557b0] text-[14px] leading-none flex-shrink-0">✦</span>
            )}
            <span className="truncate">{actionLine}</span>
          </div>
        )}
      </div>

      {/* Right: Time (mono) & Status Pill */}
      <div className="flex flex-col items-end gap-[6px] justify-center flex-shrink-0">
        {time && (
          <span className="text-[12px] font-mono text-[#666666]">
            {time}
          </span>
        )}
        {statusPill && <div>{statusPill}</div>}
      </div>
    </div>
  );
}
