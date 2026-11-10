import { InboxThread } from "@/types/inbox";

const digitsOf = (value: string) => value.replace(/\D/g, "");

/**
 * Whether an inbox thread matches the owner's search text. Looks at the people (name, email or phone, the phone also
 * by its digits so "+31 6 12" and "0612" style input both work), the unit, the subject, the ticket refs, and the text
 * of every message in the thread, not just the latest snippet.
 */
export function threadMatchesQuery(thread: InboxThread, rawQuery: string): boolean {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return true;

  const messages = thread.messages ?? [];
  const contacts = [thread.senderContact, ...messages.map((m) => m.senderContact)].filter(Boolean);
  const haystack = [
    thread.senderName,
    thread.unitLabel,
    thread.subject,
    thread.latestSnippet,
    thread.ticketNumber,
    thread.caseRef,
    ...contacts,
    ...messages.flatMap((m) => [m.senderName, m.body, m.bodyEnglish]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (haystack.includes(query)) return true;

  const queryDigits = digitsOf(query);
  const isPhoneLike = queryDigits.length >= 3 && queryDigits.length === query.replace(/[\s()+-]/g, "").length;
  return isPhoneLike && contacts.some((c) => digitsOf(c).includes(queryDigits.replace(/^0+/, "")));
}
