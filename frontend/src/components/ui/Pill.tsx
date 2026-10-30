"use client";

import React from "react";
import { cn } from "@/lib/utils";

export type PillVariant = "default" | "needs_you" | "urgent" | "outline";

export interface PillProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: PillVariant;
  dot?: boolean | "black" | "orange";
  icon?: React.ReactNode;
  children: React.ReactNode;
}

export function Pill({
  variant = "default",
  dot = false,
  icon,
  className,
  children,
  ...props
}: PillProps) {
  const variantStyles: Record<PillVariant, string> = {
    default: "bg-[#F0F0EE] text-[#444444]",
    needs_you: "bg-[#FFF1E7] text-[#B93C00] ring-1 ring-inset ring-[#F25C05]",
    urgent: "bg-[#F25C05] text-[#0A0A0A]",
    outline: "bg-transparent ring-1 ring-inset ring-[#D2D2CE] text-[#444444]",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full text-[12px] font-semibold px-2 py-[2px] leading-[18px] select-none whitespace-nowrap",
        variantStyles[variant],
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            "w-2 h-2 rounded-full flex-shrink-0",
            dot === "orange" || variant === "needs_you" ? "bg-[#F25C05]" : "bg-[#0A0A0A]"
          )}
        />
      )}
      {icon && <span className="flex-shrink-0 text-current">{icon}</span>}
      <span className="truncate">{children}</span>
    </span>
  );
}
