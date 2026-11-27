/** The sources a researched Astra answer rests on (`sources` in POST /api/agent/ask). The backend only lists rows and
 * pages its own tools returned, and builds `href` itself (a mail's case thread, a filed document's Drive file). A chip
 * opens only one of our own pages or an https URL. */

export type SourceKind = "message" | "document" | "web" | "data";

export interface AnswerSource {
  kind: SourceKind;
  ref: string;
  label: string;
  href?: string | null;
}

export interface SourceChip {
  key: string;
  kind: SourceKind;
  label: string;
  href: string | null;
}

function httpsOnly(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function safeLink(source: AnswerSource): string | null {
  const href = source.href ?? (source.kind === "web" ? source.ref : null);
  if (!href) return null;
  if (/^\/(?![/\\])/.test(href)) return href; // one of our own pages (never "//host" or "/\\host")
  return httpsOnly(href);
}

export function sourceChips(sources: AnswerSource[] | undefined | null): SourceChip[] {
  const seen = new Set<string>();
  const chips: SourceChip[] = [];
  for (const source of sources ?? []) {
    const label = source.label.trim();
    const key = `${source.kind}:${source.ref}`;
    if (!label || seen.has(key)) continue;
    seen.add(key);
    chips.push({ key, kind: source.kind, label, href: safeLink(source) });
  }
  return chips;
}
