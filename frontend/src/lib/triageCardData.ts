import { AiUnderstandingCard, TriageItem } from "@/types/dashboard";
import { InboxThread } from "@/types/inbox";

export interface TriageCardDisplayData {
  channelBadge: string; // e.g. "WhatsApp · Today 07:42"
  issueTitle: string;
  unitSubtitle: string;
  sourceIdentifier: string;
  originalMessage: string;
  translatedLine: string; // "" unless the thread carries a real translation
  detectedLanguageBadge: string;
  understanding: AiUnderstandingCard;
  whenYouApprove: string[]; // [] unless the thread names real follow-up actions
  replySnippet: string; // "" unless a draft exists
  replyTranslation?: string;
}

/** The newest message from the other party, not the owner's own reply. */
function latestIncomingBody(item: InboxThread): string {
  const incoming = [...(item.messages ?? [])].reverse().find((m) => m.sender !== "owner" && m.body);
  return incoming?.body || item.latestSnippet || "";
}

/**
 * The review card for one thread, built only from what that thread carries: its own message, its own understanding
 * and its own drafts. Anything the thread does not carry stays empty (the card then shows nothing for it) instead of
 * borrowing a scenario about another tenant.
 */
export function getTriageCardData(item: TriageItem | InboxThread | null): TriageCardDisplayData | null {
  if (!item) return null;

  const isTriageItem = "tenantMessage" in item;
  const channelName = item.channel === "whatsapp" ? "WhatsApp" : "Gmail";
  const when = isTriageItem ? item.receivedTime : item.relativeTime;
  const body = isTriageItem ? item.tenantMessage : latestIncomingBody(item);
  const summary = isTriageItem ? item.parsedSummary : item.latestSnippet || "Action required";
  const isUrgent = item.urgency === "emergency" || item.urgency === "high";
  const role = (item.recipientRole as string) === "contractor" ? "contractor" : "tenant";
  const language = !isTriageItem ? item.detectedLanguage : undefined;
  const firstDraft = isTriageItem ? item.drafts?.[0] : (item.draftProposal?.drafts?.[0] ?? item.draftProposal?.gmailDrafts?.[0]);

  return {
    channelBadge: when ? `${channelName} · ${when}` : channelName,
    issueTitle: (!isTriageItem && item.issueTitle) || (isTriageItem ? item.tenantMessage.split(".")[0] : item.subject) || summary,
    unitSubtitle: item.unitLabel,
    sourceIdentifier: item.senderContact ? `${channelName} · ${item.senderContact}` : channelName,
    originalMessage: body,
    translatedLine: (!isTriageItem && item.translatedSnippet) || "",
    detectedLanguageBadge: language ? `Reply to ${role} · ${language}` : `Reply to ${role}`,
    understanding: item.aiUnderstanding ?? {
      ticket: item.ticketNumber ? `Ticket ${item.ticketNumber}` : `New ticket ${item.caseRef}`,
      problem: `${item.category.charAt(0).toUpperCase() + item.category.slice(1)} › ${summary}`,
      unit: item.unitLabel,
      priority: isUrgent ? "Urgent" : "Normal",
    },
    whenYouApprove: item.whenYouApprove ?? [],
    replySnippet: firstDraft?.text ?? "",
    replyTranslation: isTriageItem ? item.draftTranslation : undefined,
  };
}
