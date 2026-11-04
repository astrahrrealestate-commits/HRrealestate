"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "link" | "accent";
  size?: "sm" | "default" | "lg";
  icon?: React.ReactNode;
  children?: React.ReactNode;
}

export function Button({
  variant = "ghost",
  size = "default",
  type = "button",
  icon,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  const variantStyles = {
    // Primary: Section 6.3
    primary:
      "bg-[var(--accent)] hover:brightness-95 text-[#0A0A0A] font-semibold rounded-[var(--radius-ctl)] shadow-xs active:scale-[0.99]",
    // Ghost (everything else): Section 6.3
    ghost:
      "bg-transparent text-[var(--ink)] hover:bg-[var(--selected)] rounded-[var(--radius-ctl)] active:scale-[0.99]",
    // Secondary / Outline: neutral border, white pane background
    secondary:
      "bg-[var(--pane)] text-[var(--ink)] border border-[var(--line)] hover:bg-[var(--selected)] rounded-[var(--radius-ctl)] active:scale-[0.99]",
    // Link: inline text link with underline
    link:
      "bg-transparent text-[var(--ink)] underline-offset-4 hover:underline whitespace-nowrap p-0 min-h-0 h-auto font-medium",
    // Accent: identical to primary for backwards compatibility
    accent:
      "bg-[var(--accent)] hover:brightness-95 text-[#0A0A0A] font-semibold rounded-[var(--radius-ctl)] shadow-xs active:scale-[0.99]",
  };

  const sizeStyles = {
    sm: "h-8 px-2.5 text-[13px] gap-1.5",
    default: "h-10 px-4 text-[14px] gap-2",
    lg: "h-11 px-5 text-[15px] gap-2.5",
  };

  return (
    <button
      type={type}
      suppressHydrationWarning
      className={cn(
        "inline-flex items-center justify-center font-semibold transition-all select-none cursor-pointer disabled:opacity-50 disabled:pointer-events-none focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1a73e8] focus-visible:ring-offset-2",
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
      disabled={disabled}
      {...props}
    >
      {icon && <span className="flex-shrink-0 text-current">{icon}</span>}
      {children && <span>{children}</span>}
    </button>
  );
}
