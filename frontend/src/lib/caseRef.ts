/**
 * The short reference people see for a case (`#3f9a1c`). Mirrors `app.core.ids.case_ref`: the random tail of the
 * UUIDv7, because the head is a timestamp and cases created together share it.
 */
export function caseRefTail(id: string | null | undefined): string {
  const hex = (id || "").replace(/-/g, "").toLowerCase();
  return /^[0-9a-f]{32}$/.test(hex) ? hex.slice(-6) : hex.slice(0, 6);
}

export function ticketRef(id: string | null | undefined): string {
  return `#${caseRefTail(id)}`;
}
