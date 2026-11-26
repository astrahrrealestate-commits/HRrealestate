/** The sources a researched Astra answer rests on (`sources` in POST /api/agent/ask). The backend only lists rows and
 * pages its own tools returned; a web page opens in a new tab, and only over https. */

export type SourceKind = "message" | "document" | "web" | "data";

export interface AnswerSource {
  kind: SourceKind;
  ref: string;
  label: string;
}

export interface SourceChip {
  key: string;
  kind: SourceKind;
  label: string;
  href: string | null;
}

function safeLink(source: AnswerSource): string | null {
  if (source.kind !== "web") return null;
  try {
    const url = new URL(source.ref);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
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
