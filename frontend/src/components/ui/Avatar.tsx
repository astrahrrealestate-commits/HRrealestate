"use client";

import React from "react";
import { MessageSquare, Mail, Globe, Phone } from "lucide-react";
import { cn } from "@/lib/utils";

interface AvatarProps {
  name: string;
  channel?: "whatsapp" | "gmail" | "portal" | "phone" | string;
  size?: "sm" | "default" | "lg";
  className?: string;
}

function getInitials(name: string): string {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Avatar with optional tiny channel badge (Section 5.2 & 6.1).
 * Channel icon appears in the corner, neutral ink/grey palette.
 */
export function Avatar({
  name,
  channel,
  size = "default",
  className,
}: AvatarProps) {
  const initials = getInitials(name);

  const sizeClasses = {
    sm: "w-8 h-8 text-[11px]",
    default: "w-10 h-10 text-[13px]",
    lg: "w-12 h-12 text-[15px]",
  };

  const badgeSizeClasses = {
    sm: "w-3.5 h-3.5",
    default: "w-4 h-4",
    lg: "w-4.5 h-4.5",
  };

  const iconSizeClasses = {
    sm: "w-2 h-2",
    default: "w-2.5 h-2.5",
    lg: "w-3 h-3",
  };

  const normalizedChannel = channel?.toLowerCase();

  return (
    <div className={cn("relative inline-flex flex-shrink-0 select-none", className)}>
      <div
        className={cn(
          "rounded-full bg-[var(--selected)] border border-[var(--line)] flex items-center justify-center font-semibold text-[var(--ink)]",
          sizeClasses[size]
        )}
        aria-label={name}
      >
        <span>{initials}</span>
      </div>

      {normalizedChannel && (
        <span
          className={cn(
            "absolute -bottom-0.5 -right-0.5 rounded-full bg-[var(--pane)] border border-[var(--line)] flex items-center justify-center shadow-xs",
            badgeSizeClasses[size]
          )}
          title={`Channel: ${channel}`}
        >
          {normalizedChannel.includes("whatsapp") && (
            <MessageSquare className={cn(iconSizeClasses[size], "text-[#25D366]")} strokeWidth={2.2} />
          )}
          {normalizedChannel.includes("gmail") && (
            <Mail className={cn(iconSizeClasses[size], "text-[#EA4335]")} strokeWidth={2.2} />
          )}
          {normalizedChannel.includes("portal") && (
            <Globe className={cn(iconSizeClasses[size], "text-[var(--ink-2)]")} strokeWidth={2} />
          )}
          {normalizedChannel.includes("phone") && (
            <Phone className={cn(iconSizeClasses[size], "text-[var(--ink-2)]")} strokeWidth={2} />
          )}
        </span>
      )}
    </div>
  );
}
