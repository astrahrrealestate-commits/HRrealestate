/** Display helpers for fields the API may not know: an unknown value reads "—", never 0 or "null". */
export const UNKNOWN = "—";

export function euro(amount: number | null | undefined): string {
  return amount == null ? UNKNOWN : `€ ${amount},-`;
}

/** "Floor 2 · 62 m²" with only the parts that are known; "—" when none are. */
export function specLine(floor: number | null, areaSqm: number | null): string {
  const parts = [floor == null ? null : `Floor ${floor}`, areaSqm == null ? null : `${areaSqm} m²`];
  return parts.filter(Boolean).join(" · ") || UNKNOWN;
}
