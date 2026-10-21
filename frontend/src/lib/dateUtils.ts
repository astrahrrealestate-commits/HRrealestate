import { differenceInCalendarDays, format } from "date-fns";

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
  if (!d) return `Today ${format(referenceNow, "HH:mm")}`;

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
    return `Today ${format(referenceNow, "HH:mm")}`;
  }

  const days = differenceInCalendarDays(referenceNow, dateObj);
  if (days === 0) return `Today ${format(dateObj, "HH:mm")}`;
  if (days === 1) return `Yesterday ${format(dateObj, "HH:mm")}`;
  if (days < 7 && days > 0) return `${format(dateObj, "EEE")} ${format(dateObj, "HH:mm")}`;
  return format(dateObj, "d MMM HH:mm");
}
