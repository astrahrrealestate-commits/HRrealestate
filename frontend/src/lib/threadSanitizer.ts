/**
 * Thread & Snippet Sanitization (Sections 2.5 D2, D3, D4)
 * Provides:
 * - D2: Contact display name (the server's name, else the address)
 * - D3: getSnippet() cleaner (strips system text & raw ISO strings, collapses whitespace, 90 chars)
 * - D4: threadId generation & message grouping
 */

/**
 * Section 2.5 D2:
 * The sender name on screen is the one the server gave for that sender (Reply-To first for email). With no name,
 * the address. Never a name guessed from the message text or the unit, and never a replacement for a "generic" one.
 */
export function getContactDisplayName(params: { senderName?: string; senderContact?: string }): string {
  return params.senderName?.trim() || params.senderContact?.trim() || "Unknown sender";
}

/**
 * Section 2.5 D3:
 * getSnippet(message):
 * - Last message body
 * - Strip system lines (e.g. "Incoming communication analyzed by Gemini AI agent.")
 * - Strip raw ISO timestamps (e.g. "2026-10-13T07:12:39.417000+00:00")
 * - Collapse whitespace
 * - Max 90 characters with ellipsis
 */
export function getSnippet(rawMessage: string | null | undefined, maxLength = 90): string {
  if (!rawMessage) return "";

  let text = String(rawMessage);

  // 1. Strip system text lines
  const systemPatterns = [
    /Incoming communication analyzed by Gemini AI agent\.?/gi,
    /Message analyzed by EstateOS AI agent\.?/gi,
    /External message received via (?:Gmail|WhatsApp)\.?/gi,
    /System generated notification\.?/gi,
  ];

  for (const pattern of systemPatterns) {
    text = text.replace(pattern, "");
  }

  // 2. Strip raw ISO timestamps
  text = text.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?/g, "");

  // 3. Strip timestamp prefix patterns like "2026-10-13 07:12:39 Mevr. de Vries:"
  text = text.replace(/^\d{4}-\d{2}-\d{2}[^:]*:\s*/gm, "");

  // 4. Collapse whitespace (newlines, tabs, multiple spaces) to single space
  text = text.replace(/\s+/g, " ").trim();

  // 5. Truncate to maxLength (default 90 chars)
  if (text.length > maxLength) {
    return text.slice(0, maxLength - 1).trimEnd() + "…";
  }

  return text;
}

/**
 * Section 2.5 D4:
 * Generates a unified threadId from (unit + contact + ticket)
 * so multiple messages for the same incident/unit are grouped into one conversation thread.
 */
export function getUnifiedThreadId(params: {
  unitLabel?: string;
  contactName?: string;
  senderContact?: string;
  ticketNumber?: string;
  caseRef?: string;
  fallbackId?: string;
}): string {
  const unit = (params.unitLabel || "general").toLowerCase().replace(/[^a-z0-9]/g, "-");
  const contact = (params.contactName || params.senderContact || "contact").toLowerCase().replace(/[^a-z0-9]/g, "-");
  const ticket = (params.ticketNumber || params.caseRef || "general").toLowerCase().replace(/[^a-z0-9]/g, "-");

  const key = `${unit}_${contact}_${ticket}`.replace(/-+/g, "-");
  return key || params.fallbackId || `thread-${Math.random().toString(36).substring(2, 9)}`;
}
