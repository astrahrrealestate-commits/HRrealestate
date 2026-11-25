import { InboxThread } from "@/types/inbox";
import { BACKEND_BASE_URL, apiFetch } from "@/lib/backend";
import { caseRefTail, ticketRef } from "@/lib/caseRef";
import { getContactDisplayName, getSnippet, getUnifiedThreadId } from "@/lib/selectors";

/**
 * Fetches a single inbox thread directly by case ID (`GET /api/inbox/threads/{case_id}`).
 * Used when deep-linking from Dashboard (`?thread=case-...`) so both WhatsApp and Gmail
 * ingested threads open immediately even if older than the initial 20-thread inbox page.
 */
export async function fetchInboxThreadById(caseId: string): Promise<InboxThread | null> {
  const cleanId = caseId.trim();
  if (!cleanId) return null;
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(cleanId)}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const t = data?.thread;
    if (!t || typeof t !== "object") return null;

    const channel = t.channel === "whatsapp" || t.channel === "gmail" ? t.channel : "gmail";
    const gDrafts = Array.isArray(t.gmailDrafts) ? t.gmailDrafts : [];
    const wDrafts = Array.isArray(t.whatsappDrafts) ? t.whatsappDrafts : [];
    const activeDrafts = channel === "whatsapp" ? wDrafts : gDrafts;
    const unitLabel = t.unit || t.unitLabel || "Unassigned";
    const rawSnippet = t.lastMessageSnippet || t.latestSnippet || "";
    const cleanSnippet = getSnippet(rawSnippet);
    const senderContact = t.sender?.contact || t.senderContact || "";
    const resolvedSenderName = getContactDisplayName({
      senderName: t.sender?.name || t.senderName,
      senderContact,
      unitLabel,
      messageBody: rawSnippet,
    });
    const unifiedThreadId = getUnifiedThreadId({
      unitLabel,
      contactName: resolvedSenderName,
      senderContact,
      ticketNumber: t.ticketNumber || t.caseRef,
      fallbackId: t.id,
    });
    const isApproved = t.status === "approved" || t.status === "replied";
    const rawMsgs = Array.isArray(t.messages) ? t.messages : [];
    const lastMsg = rawMsgs.length > 0 ? rawMsgs[rawMsgs.length - 1] : null;
    const lastMsgIsOutbound = Boolean(
      lastMsg && (lastMsg.sender === "owner" || lastMsg.direction === "outbound" || lastMsg.isIncoming === false)
    );

    return {
      id: t.id || `case-${t.caseId || cleanId}`,
      threadId: unifiedThreadId,
      caseRef: t.caseRef || `#cs-${caseRefTail(t.caseId || t.id)}`,
      ticketNumber: t.ticketNumber || t.aiUnderstanding?.ticket || ticketRef(t.caseId || t.id),
      caseId: t.caseId || t.id,
      channel,
      senderKind:
        t.senderKind ||
        (t.audience === "contractors"
          ? "contractor"
          : t.audience === "inquiries"
            ? "prospect"
            : t.audience === "tenants"
              ? "tenant"
              : "contact"),
      recipientRole:
        t.audience === "contractors" || t.recipientRole === "contractor"
          ? "contractor"
          : t.audience === "inquiries"
            ? "inquiry"
            : t.audience === "others" || t.recipientRole === "contact"
              ? "contact"
              : "tenant",
      recipientRoleDetail:
        t.recipientRoleDetail ||
        t.sender?.role ||
        (t.audience === "contractors" ? "Contractor" : t.audience === "others" ? "Contact" : "Tenant"),
      externalMessageId: t.externalMessageId || t.sourceIdentifier || t.id,
      externalThreadId: t.externalThreadId || t.caseId || t.id,
      approvalId: t.approvalId || t.caseId || t.id,
      subject: t.subject || t.title,
      senderName: resolvedSenderName,
      senderContact,
      unitLabel,
      buildingName: t.buildingName || "Centrum Portfolio",
      category: t.category || "other",
      urgency: t.urgency || "normal",
      status: t.status || "needs_approval",
      isRead: typeof t.isRead === "boolean" ? t.isRead : undefined,
      snoozedUntil: t.snoozedUntil ?? null,
      detectedLanguage: t.detectedLanguage || "Dutch (detected)",
      aiUnderstanding: t.aiUnderstanding,
      receivedAt: t.receivedAt || new Date().toISOString(),
      relativeTime: t.timestamp || "Today",
      latestSnippet: cleanSnippet,
      inResponseToSnippet: cleanSnippet,
      caseSummary: t.aiSummary || t.caseSummary || "",
      attachments: t.attachments || [],
      messages: rawMsgs.map((m: any) => ({
        id: m.id || `msg-${Math.random()}`,
        sender: m.sender === "owner" ? "owner" : "tenant",
        senderName: m.senderName || "Sender",
        senderContact: m.senderContact || "",
        sentAt: m.sentAt || t.receivedAt || new Date().toISOString(),
        timeFormatted: m.timeFormatted || m.timestamp || "Today",
        body: m.body || m.content || "",
        bodyHtml: m.bodyHtml || null,
        bodyEnglish: m.bodyEnglish || undefined,
        bodyDutch: m.bodyDutch || undefined,
        language: m.language,
        channel: m.channel || channel,
        replyTo: m.replyTo,
        attachments: m.attachments || [],
      })),
      draftProposal:
        !isApproved && !lastMsgIsOutbound && (gDrafts.length > 0 || wDrafts.length > 0)
          ? {
              confidence: (t.aiConfidence || 95) / 100,
              recommendedAction: t.aiSummary || "Review and approve staged draft reply.",
              activeChannel: channel,
              persona: t.draftPersona || undefined,
              whatsappDrafts: wDrafts,
              gmailDrafts: gDrafts,
              drafts: activeDrafts.length > 0 ? activeDrafts : gDrafts.length > 0 ? gDrafts : wDrafts,
            }
          : undefined,
    };
  } catch {
    return null;
  }
}
