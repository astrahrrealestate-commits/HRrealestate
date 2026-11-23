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

const pad = (n: number) => String(n).padStart(2, "0");

/** "10-11-2026" in the company's zone, the same form the API uses for lease dates. */
export function formatDate(date: Date): string {
  const p = localParts(date);
  return `${pad(p.day)}-${pad(p.month)}-${p.year}`;
}

export function formatStamp(date: Date): string {
  const p = localParts(date);
  return `${formatDate(date)} ${p.hh}:${p.mm}`;
}

const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const MONTHS_SHORT = MONTHS_LONG.map((m) => m.slice(0, 3));

const weekdayLong = new Intl.DateTimeFormat("en-GB", { timeZone: APP_TIME_ZONE, weekday: "long" });

/** "Thursday 15 October" in the company's zone. */
export function formatLongDay(date: Date): string {
  const p = localParts(date);
  return `${weekdayLong.format(date)} ${p.day} ${MONTHS_LONG[p.month - 1]}`;
}

/** "15 Oct" in the company's zone. */
export function formatShortDate(date: Date): string {
  const p = localParts(date);
  return `${p.day} ${MONTHS_SHORT[p.month - 1]}`;
}

/** "Thu 15 Oct" in the company's zone. */
export function formatWeekdayDate(date: Date): string {
  return `${localParts(date).weekday} ${formatShortDate(date)}`;
}

/** The instant at which the company's wall clock reads `hour:minute` on the local day `dayNumber` (see localDayNumber). */
export function localWallToDate(dayNumber: number, hour: number, minute: number): Date {
  const wall = dayNumber * 86_400_000 + (hour * 60 + minute) * 60_000;
  let guess = wall;
  for (let i = 0; i < 2; i++) {
    const p = localParts(new Date(guess));
    const shown = Date.UTC(p.year, p.month - 1, p.day, Number(p.hh), Number(p.mm));
    guess += wall - shown;
  }
  return new Date(guess);
}
