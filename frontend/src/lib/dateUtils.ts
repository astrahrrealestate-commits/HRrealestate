import { differenceInCalendarDays, format } from "date-fns";
import { formatClock, localDayNumber, localParts } from "@/lib/clock";

/**
 * Format timestamp according to Section 3.5:
 * - Today: HH:mm (e.g. "08:15")
 * - Yesterday: "Yesterday"
 * - Within 7 days: Day abbreviation (e.g. "Mon")
 * - Older: Day and short month (e.g. "12 Oct")
 */
const STATIC_NOW = new Date("2026-10-15T12:00:00Z");

export function formatListTime(d: Date | string | number | null | undefined, now?: Date): string {
  // If running in SSR/prerender context without window, use deterministic timestamp to prevent Next.js 16 dynamic prerender error
  const referenceNow = now ?? (typeof window !== "undefined" ? new Date() : STATIC_NOW);
  if (!d) {
    return `Today ${formatClock(referenceNow)}`;
  }

  if (typeof d === "string") {
    const trimmed = d.trim();
    if (trimmed.startsWith("Today") || trimmed.startsWith("Yesterday")) {
      return trimmed;
    }
    if (/^\d{1,2}:\d{2}$/.test(trimmed)) {
      return `Today ${trimmed}`;
    }
  }

  const dateObj = typeof d === "string" || typeof d === "number" ? new Date(d) : d;
  if (!dateObj || isNaN(dateObj.getTime())) {
    if (typeof d === "string" && d.trim().length > 0) {
      return d.trim();
    }
    return `Today ${formatClock(referenceNow)}`;
  }

  const clock = formatClock(dateObj);
  const diffDays = localDayNumber(referenceNow) - localDayNumber(dateObj);
  if (diffDays === 0) return `Today ${clock}`;
  if (diffDays === 1) return `Yesterday ${clock}`;
  const local = localParts(dateObj);
  if (diffDays < 7 && diffDays > 0) return `${local.weekday} ${clock}`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${local.day} ${months[local.month - 1]} ${clock}`;
}
