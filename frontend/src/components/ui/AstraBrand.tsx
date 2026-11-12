import React from "react";
import { cn } from "@/lib/utils";

/**
 * Custom geometric celestial compass-star emblem for Astra (replaces generic Sparkles/emojis).
 */
export function AstraIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("w-4 h-4 shrink-0", className)}
    >
      {/* Outer precision orbital ring */}
      <circle
        cx="12"
        cy="12"
        r="9.25"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeOpacity="0.35"
      />
      {/* Four-point architectural star */}
      <path
        d="M12 3.25L14.2 9.8L20.75 12L14.2 14.2L12 20.75L9.8 14.2L3.25 12L9.8 9.8L12 3.25Z"
        fill="currentColor"
        fillOpacity="0.18"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      {/* Crisp center core */}
      <circle cx="12" cy="12" r="1.65" fill="currentColor" />
    </svg>
  );
}

/**
 * Stylized typographic wordmark for Astra on dark or light surfaces.
 */
export function AstraWordmark({
  variant = "dark",
  className,
}: {
  variant?: "dark" | "light";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-heading font-bold uppercase tracking-[0.16em] bg-clip-text text-transparent select-none leading-none",
        variant === "dark"
          ? "bg-gradient-to-r from-white via-sky-100 to-cyan-300"
          : "bg-gradient-to-r from-[#0A1B2F] via-[#1557b0] to-[#0284c7]",
        className
      )}
    >
      Astra
    </span>
  );
}

