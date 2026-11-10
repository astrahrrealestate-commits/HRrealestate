/**
 * Every time the owner sees is the company's local clock, 24 h. The browser's own zone (an owner travelling, a dev
 * machine in India) and UTC are never shown. Mirrors the server's `company.timezone` default.
 */
export const APP_TIME_ZONE = process.env.NEXT_PUBLIC_TIME_ZONE || "Europe/Amsterdam";

const parts = new Intl.DateTimeFormat("en-GB", {
  timeZone: APP_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  weekday: "short",
  hourCycle: "h23",
});

export interface LocalParts {
  year: number;
  month: number; // 1-12
  day: number;
  hh: string;
  mm: string;
  weekday: string; // "Mon"
}

export function localParts(date: Date): LocalParts {
  const get = Object.fromEntries(parts.formatToParts(date).map((p) => [p.type, p.value]));
  return {
    year: Number(get.year),
    month: Number(get.month),
    day: Number(get.day),
    hh: get.hour,
    mm: get.minute,
    weekday: get.weekday,
  };
}

/** "09:30" in the company's zone. */
export function formatClock(date: Date): string {
  const p = localParts(date);
  return `${p.hh}:${p.mm}`;
}

/** Whole days since the epoch of the local calendar date, so two instants subtract to local calendar days. */
export function localDayNumber(date: Date): number {
  const p = localParts(date);
  return Math.floor(Date.UTC(p.year, p.month - 1, p.day) / 86_400_000);
}
