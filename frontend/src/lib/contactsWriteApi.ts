/** Adding, naming and classifying contacts (`POST /api/contacts`, `PATCH /api/contacts/{id}`). */

import { apiFetch, BACKEND_BASE_URL } from "@/lib/backend";
import type { ContactItem } from "@/data/contactsMockData";

/** What the owner picks when adding someone. "maintenance" is a contractor whose trade starts as Maintenance. */
export type ContactType = "tenant" | "contractor" | "maintenance" | "utility" | "municipal" | "owner" | "other";

export const CONTACT_TYPES: ReadonlyArray<{ value: ContactType; label: string; hint: string; needsTrade: boolean }> = [
  { value: "tenant", label: "Tenant", hint: "Rents one of your units", needsTrade: false },
  { value: "contractor", label: "Contractor", hint: "Plumber, electrician, painter…", needsTrade: true },
  { value: "maintenance", label: "Maintenance", hint: "Caretaker, cleaner, handyman…", needsTrade: true },
  { value: "utility", label: "Utility", hint: "Energy, water, internet", needsTrade: false },
  { value: "municipal", label: "Municipality", hint: "Gemeente, housing authority", needsTrade: false },
  { value: "owner", label: "Owner", hint: "A property owner", needsTrade: false },
  { value: "other", label: "Other", hint: "Anyone else you deal with", needsTrade: true },
];

export interface ContactDraft {
  name: string;
  type: ContactType;
  trade: string;
  email: string;
  phone: string;
}

/** A contact as the API returns it: the list shape plus where it came from. */
export type SavedContact = ContactItem & {
  source: "brixx" | "directory";
  unclassified: boolean;
  /** The stored trade or role, empty when none. */
  trade?: string;
};

export type ContactResult = { ok: true; data: SavedContact } | { ok: false; error: string };

/** The API's category for a picked type, and the trade to store with it. */
function toApi(draft: ContactDraft): { category: string; trade: string | null } {
  const trade = draft.trade.trim();
  if (draft.type === "maintenance") return { category: "contractor", trade: trade || "Maintenance" };
  return { category: draft.type, trade: trade || null };
}

/** The type a stored contact shows as when it is edited (a maintenance person is a contractor with that trade). */
export function typeOf(contact: Pick<ContactItem, "category">): ContactType {
  return contact.category;
}

function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (status === 403) return "Your profile cannot add contacts.";
  return "Something went wrong. Try again.";
}

async function send(path: string, method: "POST" | "PATCH", payload: unknown): Promise<ContactResult> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/contacts${path}`, {
      method,
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000),
    });
    const body = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: body as SavedContact };
    return { ok: false, error: messageFrom(body, res.status) };
  } catch {
    return { ok: false, error: "Could not reach the server. Check your connection and try again." };
  }
}

export function addContact(draft: ContactDraft): Promise<ContactResult> {
  const { category, trade } = toApi(draft);
  return send("", "POST", {
    name: draft.name.trim(),
    category,
    trade,
    email: draft.email.trim() || null,
    phone: draft.phone.trim() || null,
  });
}

export function classifyContact(id: string, draft: Pick<ContactDraft, "name" | "type" | "trade">): Promise<ContactResult> {
  const { category, trade } = toApi({ ...draft, email: "", phone: "" });
  return send(`/${encodeURIComponent(id)}`, "PATCH", { name: draft.name.trim(), category, trade });
}
