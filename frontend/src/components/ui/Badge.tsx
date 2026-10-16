"use client";

import React from "react";
import { Pill, PillVariant, PillProps } from "./Pill";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "neutral" | "critical" | "accent" | PillVariant;
  dot?: boolean | "neutral" | "critical" | "live" | "black" | "orange";
  icon?: React.ReactNode;
  children: React.ReactNode;
}

export function Badge({
  variant = "neutral",
  dot = false,
  icon,
  className,
  children,
  ...props
}: BadgeProps) {
  let mappedVariant: PillVariant = "default";
  if (variant === "critical" || variant === "urgent") {
    mappedVariant = "urgent";
  } else if (variant === "accent" || variant === "needs_you") {
    mappedVariant = "needs_you";
  } else if (variant === "outline") {
    mappedVariant = "outline";
  }

  const mappedDot = dot ? (mappedVariant === "urgent" || mappedVariant === "needs_you" ? "orange" : "black") : false;

  return (
    <Pill
      variant={mappedVariant}
      dot={mappedDot}
      icon={icon}
      className={className}
      {...props}
    >
      {children}
    </Pill>
  );
}

export { Pill };
