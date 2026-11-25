/**
 * Thread & Snippet Sanitization (Sections 2.5 D2, D3, D4)
 * Provides:
 * - D2: Contact display name matching (unit / signature / email fallback)
 * - D3: getSnippet() cleaner (strips system text & raw ISO strings, collapses whitespace, 90 chars)
 * - D4: threadId generation & message grouping
 */

// Known unit tenant mappings for reliable display name resolution
export const UNIT_CONTACT_MAP: Record<string, string> = {
  "pieter floriszstraat 1 c": "Pieter Bakker",
  "dorpsstraat 54 e": "Rick de Boer",
  "singel 412": "Marloes Jansen",
  "prinses marijkestraat 2 a": "Daan Vermeulen",
  "keizersgracht 142 b": "Sanne Meijer",
  "weteringschans 88": "Bas van Leeuwen",
  "herengracht 210": "Sophie de Vries",
};

/**
 * Section 2.5 D2:
 * Resolves proper contact display name by:
 * 1. Unit label match from known directory
 * 2. Signature match at end of message (e.g. "Groet, Pieter", "Met vriendelijke groet, Rick")
 * 3. Falling back to senderName (ignoring generic test mailbox names if signature found)
 * 4. Falling back to senderContact / email
 */
export function getContactDisplayName(params: {
  senderName?: string;
  senderContact?: string;
  unitLabel?: string;
  messageBody?: string;
}): string {
  const { senderName = "", senderContact = "", unitLabel = "", messageBody = "" } = params;

  // 1. If a valid external senderName is provided (e.g. contractor, tenant, company), preserve it!
  const isGenericOrOwner =
    !senderName.trim() ||
    /^(?:suryansh|harjot(?:\s+singh)?|me|estateos|unknown|system|user|tenant|owner|admin)$/i.test(
      senderName.trim()
    );

  if (!isGenericOrOwner) {
    return senderName.trim();
  }

  // 2. Check for signature in message body (e.g. "Groet, Pieter", "Met vriendelijke groet, Rick")
  if (messageBody) {
    const signatureMatch = messageBody.match(
      /(?:Groet(?:en)?|Met vriendelijke groet(?:en)?|Gr\.?|Regards|Best(?: regards)?|Thanks)[,\s\r\n]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)/i
    );
    if (signatureMatch && signatureMatch[1]) {
      const parsedName = signatureMatch[1].trim();
      if (parsedName.length > 1 && !/^(?:en|de|het|van|in)$/i.test(parsedName)) {
        return parsedName;
      }
    }
  }

  // 3. Fallback: check known unit directory
  const normalizedUnit = unitLabel.toLowerCase().trim();
  if (normalizedUnit) {
    for (const [unitKey, contactName] of Object.entries(UNIT_CONTACT_MAP)) {
      if (normalizedUnit.includes(unitKey) || unitKey.includes(normalizedUnit)) {
        return contactName;
      }
    }
  }

  // 4. Fallback to senderContact or cleaned email
  if (senderContact) {
    const emailPrefix = senderContact.split("@")[0].replace(/[._-]/g, " ");
    return emailPrefix
      .split(" ")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }

  return senderName || "Tenant";
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

  // 1b. Strip quoted reply chains (e.g. "Op ... schreef:", "On ... wrote:", or lines starting with ">")
  const quoteDelimiterRegex = /(?:\r?\n)+(?:On\s+[^\n]+?\bwrote:|Op\s+[^\n]+?\bschreef|.+?\bużytkownik\s+[^\n]+?\bnapisał:|-----Original Message-----|-----Oorspronkelijk bericht-----|From:\s*[^\n]+\nSent:\s*|Van:\s*[^\n]+\nVerzonden:\s*|>[\s\S]*)/i;
  const quoteMatch = text.search(quoteDelimiterRegex);
  if (quoteMatch > 0) {
    text = text.slice(0, quoteMatch);
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
