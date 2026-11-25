/**
 * Single source of truth for counts and filters (Section 6.4 & 2.5 D1).
 * Used by Today StatLine, Inbox tab, nav badge, and Maintenance header.
 */

export interface ThreadCountTarget {
  id?: string;
  status?: string;
  urgent?: boolean;
  urgency?: "emergency" | "high" | "normal" | "low" | string;
  snoozedUntil?: string | null;
  [key: string]: any;
}

const URGENCY_RANK: Record<string, number> = {
  emergency: 0,
  high: 1,
  normal: 2,
  low: 3,
};

function urgencyRank(t: ThreadCountTarget): number {
  if (t?.urgency && t.urgency in URGENCY_RANK) return URGENCY_RANK[t.urgency];
  return t?.urgent ? 1 : 2;
}

function isActivelySnoozedTarget(t: ThreadCountTarget): boolean {
  if (!t?.snoozedUntil) return false;
  const until = new Date(t.snoozedUntil).getTime();
  return !Number.isNaN(until) && until > Date.now();
}

/**
 * Check if a single thread requires Harjot's attention.
 */
export function isNeedsYou(t: ThreadCountTarget): boolean {
  return t?.status === "needs_you" || t?.status === "needs_approval";
}

/**
 * Check if a single thread is urgent.
 */
export function isUrgent(t: ThreadCountTarget): boolean {
  return Boolean(t?.urgent) || t?.urgency === "emergency" || t?.urgency === "high";
}

/**
 * Filter threads that require Harjot's attention.
 * Handles both "needs_you" (redesign spec) and "needs_approval" (current API).
 */
export function needsYou<T extends ThreadCountTarget>(threads: T[]): T[] {
  if (!Array.isArray(threads)) return [];
  return threads
    .filter((t) => isNeedsYou(t) && !isActivelySnoozedTarget(t))
    .sort((a, b) => urgencyRank(a) - urgencyRank(b));
}

/**
 * Filter threads that are both needs_you and urgent.
 */
export function urgent<T extends ThreadCountTarget>(threads: T[]): T[] {
  if (!Array.isArray(threads)) return [];
  return needsYou(threads).filter(
    (t) => Boolean(t.urgent) || t.urgency === "emergency" || t.urgency === "high"
  );
}

/**
 * Returns exact count of threads needing Harjot's attention.
 */
export function needsYouCount(threads: ThreadCountTarget[]): number {
  return needsYou(threads).length;
}

/**
 * Returns exact count of urgent threads needing Harjot's attention.
 */
export function urgentCount(threads: ThreadCountTarget[]): number {
  return urgent(threads).length;
}

import {
  UNIT_CONTACT_MAP,
  getContactDisplayName,
  getSnippet,
  getUnifiedThreadId,
} from "./threadSanitizer";

export {
  UNIT_CONTACT_MAP,
  getContactDisplayName,
  getSnippet,
  getUnifiedThreadId,
};
