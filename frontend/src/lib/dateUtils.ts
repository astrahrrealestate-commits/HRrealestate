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
  if (!d) {
    const hh = String(referenceNow.getUTCHours()).padStart(2, "0");
    const mm = String(referenceNow.getUTCMinutes()).padStart(2, "0");
    return `Today ${hh}:${mm}`;
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
    const hh = String(referenceNow.getUTCHours()).padStart(2, "0");
    const mm = String(referenceNow.getUTCMinutes()).padStart(2, "0");
    return `Today ${hh}:${mm}`;
  }

  const hh = String(dateObj.getUTCHours()).padStart(2, "0");
  const mm = String(dateObj.getUTCMinutes()).padStart(2, "0");
  const refDay = referenceNow.toISOString().slice(0, 10);
  const objDay = dateObj.toISOString().slice(0, 10);

  if (refDay === objDay) return `Today ${hh}:${mm}`;
  const diffDays = Math.round((new Date(refDay).getTime() - new Date(objDay).getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays === 1) return `Yesterday ${hh}:${mm}`;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const daysShort = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  if (diffDays < 7 && diffDays > 0) return `${daysShort[dateObj.getUTCDay()]} ${hh}:${mm}`;
  return `${dateObj.getUTCDate()} ${months[dateObj.getUTCMonth()]} ${hh}:${mm}`;
}
