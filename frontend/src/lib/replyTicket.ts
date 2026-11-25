/** Who a reply from a thread card goes to, and how a Dutch tenant draft greets them. */

const NO_NAME = "huurder";

/** The first name to greet; "huurder" when there is only an address, a number or nothing. */
export function greetingName(name?: string): string {
  const first = name?.trim().split(/\s+/)[0] ?? "";
  if (!first || first.includes("@") || /^\+?[\d\s()-]+$/.test(first) || name?.trim() === "Unknown sender") {
    return NO_NAME;
  }
  return first;
}

type Addressed = { tenantName?: string; tenantPhone?: string; tenantDraft?: string };
type Sender = { senderName?: string; senderContact?: string };

/**
 * The ticket as the reply side of a thread card must show it. The name, the address and the greeting belong to the
 * sender of the thread's latest mail, which can differ from the ticket's tenant. The rest of the ticket is unchanged.
 */
export function replyTicket<T extends Addressed>(ticket: T, thread: Sender): T {
  const name = thread.senderName?.trim();
  if (!name) return ticket;
  const tenantPhone = thread.senderContact || "";
  if (name === ticket.tenantName) return { ...ticket, tenantPhone: tenantPhone || ticket.tenantPhone };
  return {
    ...ticket,
    tenantName: name,
    tenantPhone,
    tenantDraft: `Beste ${greetingName(name)}, we hebben je bericht ontvangen en komen er zo snel mogelijk op terug. Met vriendelijke groet, Harjot`,
  };
}
