import { SHOWN_CATEGORIES, categoryLabel, type BusinessCategory } from "@/lib/categoryLabels";
import type { CategorySummaryItem } from "@/lib/api";

export { SHOWN_CATEGORIES, categoryLabel, type BusinessCategory };
export type DashboardTab = "all" | BusinessCategory;
export type UrgencyFilter = "all" | "emergency" | "high";

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
