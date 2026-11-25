import { AlertCircle, Check, CheckCheck, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Tick } from "@/lib/chats";

const LABELS: Record<Tick, string> = {
  pending: "Sending",
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Failed to send",
};

/** WhatsApp-style delivery tick: clock, one grey tick, two grey ticks, two blue ticks, or a red alert. */
export function TickIcon({ tick, className }: { tick: Tick; className?: string }) {
  const base = cn("w-3.5 h-3.5 shrink-0", className);
  const label = LABELS[tick];
  switch (tick) {
    case "pending":
      return <Clock className={cn(base, "text-[var(--ink-3)]")} aria-label={label} />;
    case "sent":
      return <Check className={cn(base, "text-[var(--ink-3)]")} aria-label={label} />;
    case "delivered":
      return <CheckCheck className={cn(base, "text-[var(--ink-3)]")} aria-label={label} />;
    case "read":
      return <CheckCheck className={cn(base, "text-sky-500")} aria-label={label} />;
    case "failed":
      return <AlertCircle className={cn(base, "text-rose-500")} aria-label={label} />;
  }
}
