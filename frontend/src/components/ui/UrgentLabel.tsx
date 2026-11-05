"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface UrgentLabelProps {
  className?: string;
  children?: React.ReactNode;
}

/**
 * Section 3.2:
 * Urgent is the word "Urgent" in --accent-ink (#1557b0), 12px, font-semibold, no fill, no pill.
 */
export function UrgentLabel({ className, children = "Urgent" }: UrgentLabelProps) {
  return (
    <span
      className={cn(
        "text-[12px] font-semibold text-[var(--accent-ink)] leading-none select-none tracking-tight",
        className
      )}
    >
      {children}
    </span>
  );
}
