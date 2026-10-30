"use client";

import React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface SectionHeaderProps {
  title: string;
  count?: number | string;
  actionText?: string;
  actionHref?: string;
  onAction?: () => void;
  className?: string;
}

/**
 * SectionHeader implements Section 3.1, 4 & T4:
 * - Clean text heading (16px, font-semibold) with no enclosing card.
 * - Optional count badge / text.
 * - Optional right-aligned action link with non-wrapping arrow (T4).
 */
export function SectionHeader({
  title,
  count,
  actionText,
  actionHref,
  onAction,
  className,
}: SectionHeaderProps) {
  return (
    <div
      className={cn(
        "flex items-center justify-between py-2 text-[var(--ink)]",
        className
      )}
    >
      <h3 className="text-[16px] font-semibold text-[var(--ink)] tracking-tight leading-snug">
        {title}
        {count !== undefined && (
          <span className="text-[var(--ink-3)] font-normal ml-1.5 tabular-nums">
            ({count})
          </span>
        )}
      </h3>

      {actionText && (
        actionHref ? (
          <Link
            href={actionHref}
            className="text-[13px] font-medium text-[var(--ink)] hover:underline underline-offset-4 whitespace-nowrap inline-flex items-center gap-1 transition-colors"
          >
            {actionText}
          </Link>
        ) : (
          <button
            type="button"
            onClick={onAction}
            className="text-[13px] font-medium text-[var(--ink)] hover:underline underline-offset-4 whitespace-nowrap inline-flex items-center gap-1 transition-colors cursor-pointer bg-transparent border-none p-0"
          >
            {actionText}
          </button>
        )
      )}
    </div>
  );
}
