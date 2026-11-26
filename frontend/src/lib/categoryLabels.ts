/** The six business categories (backend `app/contracts/categories.py`), in display order. `spam` is never shown. */
export const SHOWN_CATEGORIES = ["maintenance", "finance", "legal", "business", "administration", "new_projects"] as const;

export type BusinessCategory = (typeof SHOWN_CATEGORIES)[number];

const LABELS: Record<BusinessCategory, { en: string; nl: string }> = {
  maintenance: { en: "Maintenance", nl: "Onderhoud" },
  finance: { en: "Finance", nl: "Financiën" },
  legal: { en: "Legal", nl: "Juridisch" },
  business: { en: "Business", nl: "Zakelijk" },
  administration: { en: "Administration", nl: "Administratie" },
  new_projects: { en: "New projects", nl: "Nieuwe projecten" },
};

export function isBusinessCategory(value: unknown): value is BusinessCategory {
  return typeof value === "string" && (SHOWN_CATEGORIES as readonly string[]).includes(value);
}

/** The display name of a category; null for spam, old values and anything unknown. */
export function categoryLabel(category: string | undefined | null, lang: "en" | "nl" = "en"): string | null {
  return isBusinessCategory(category) ? LABELS[category][lang] : null;
}
