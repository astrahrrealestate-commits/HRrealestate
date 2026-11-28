import { SHOWN_CATEGORIES, categoryLabel, type BusinessCategory } from "@/lib/categoryLabels";
import type { CategorySummaryItem } from "@/lib/api";

export { SHOWN_CATEGORIES, categoryLabel, type BusinessCategory };
export type DashboardTab = "all" | BusinessCategory;
export type UrgencyFilter = "all" | "emergency" | "high" | "low";

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function formatPeriodLabel(period: string): string {
  if (!period || period === "all") return "All time";
  if (period === "this_week") return "This week";
  if (/^\d{4}-\d{2}$/.test(period)) {
    const [y, m] = period.split("-");
    const idx = Number(m) - 1;
    return idx >= 0 && idx < 12 ? `${MONTH_NAMES[idx]} ${y}` : period;
  }
  if (/^\d{4}$/.test(period)) return `Year ${period}`;
  return period;
}

export function extractPeriodYears(periods: readonly string[]): string[] {
  const years = new Set<string>();
  for (const p of periods) {
    const m = /^(\d{4})-\d{2}$/.exec(p);
    if (m) years.add(m[1]);
  }
  return Array.from(years).sort((a, b) => b.localeCompare(a));
}

export function fallbackCategorySummaries(): CategorySummaryItem[] {
  return SHOWN_CATEGORIES.map((category) => ({
    category,
    label: categoryLabel(category) ?? category,
    open_actions: 0,
    urgent: 0,
  }));
}

/**
 * Picks the category with the most urgent actions on first load.
 * Ties break by total open actions, then by canonical category display order.
 */
export function pickInitialCategory(summaries: readonly CategorySummaryItem[]): BusinessCategory {
  if (!summaries.length) return SHOWN_CATEGORIES[0];
  let best = summaries[0];
  for (const candidate of summaries.slice(1)) {
    if (candidate.urgent !== best.urgent) {
      if (candidate.urgent > best.urgent) best = candidate;
      continue;
    }
    if (candidate.open_actions !== best.open_actions) {
      if (candidate.open_actions > best.open_actions) best = candidate;
    }
  }
  return best.category;
}

/**
 * Empty categories intentionally show neither an open count nor an urgent dot.
 */
export function tabDisplay(summary: CategorySummaryItem): {
  label: string;
  count: number | null;
  hasUrgent: boolean;
} {
  return {
    label: categoryLabel(summary.category) ?? summary.label,
    count: summary.open_actions > 0 ? summary.open_actions : null,
    hasUrgent: summary.urgent > 0,
  };
}
