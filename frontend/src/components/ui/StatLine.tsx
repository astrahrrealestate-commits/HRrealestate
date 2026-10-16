"use client";

import React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface StatItem {
  count: number | string;
  label: string;
  urgent?: boolean;
  href?: string;
  onClick?: () => void;
}

export interface StatLineProps {
  items: StatItem[];
  divider?: React.ReactNode;
  className?: string;
}

/**
 * StatLine implements Section 4, 2.3 (T6) & 5.3:
 * Inline stats separated by dividers with no cards or boxes.
 * e.g. "10 need you  |  1 urgent  |  142 handled this week"
 * Counts can be links if href or onClick is provided.
 */
export function StatLine({
  items,
  divider = <span className="text-[var(--line)] select-none">|</span>,
  className,
}: StatLineProps) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 text-[14px] text-[var(--ink-2)]",
        className
      )}
    >
      {items.map((item, index) => {
        const isUrgent = item.urgent;
        const countClasses = cn(
          "font-semibold tabular-nums",
          isUrgent ? "text-[var(--accent-ink)]" : "text-[var(--ink)]"
        );

        const content = (
          <span className="inline-flex items-center gap-1.5 transition-colors">
            <span className={countClasses}>{item.count}</span>
            <span className={isUrgent ? "text-[var(--accent-ink)] font-medium" : "text-[var(--ink-2)]"}>
              {item.label}
            </span>
          </span>
        );

        return (
          <React.Fragment key={index}>
            {index > 0 && <span className="flex items-center">{divider}</span>}

            {item.href ? (
              <Link
                href={item.href}
                className="hover:underline underline-offset-4 cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)] rounded"
              >
                {content}
              </Link>
            ) : item.onClick ? (
              <button
                type="button"
                onClick={item.onClick}
                className="hover:underline underline-offset-4 cursor-pointer bg-transparent border-none p-0 text-left focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent)] rounded"
              >
                {content}
              </button>
            ) : (
              content
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}
