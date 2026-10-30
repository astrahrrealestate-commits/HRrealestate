"use client";

import React from "react";
import { cn } from "@/lib/utils";

interface StatusTextProps {
  status?: string;
  children?: React.ReactNode;
  className?: string;
}

/**
 * Section 3.1 & 3.2:
 * Status words are plain text in grey (--ink-3), never coloured pills or chips.
 */
export function StatusText({ status, children, className }: StatusTextProps) {
  const content = children || status || "";
  return (
    <span
      className={cn(
        "text-[13px] text-[var(--ink-3)] font-normal leading-normal",
        className
      )}
    >
      {content}
    </span>
  );
}
