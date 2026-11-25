import { ChannelType, UrgencyLevel, DraftOption, RecipientRole, AiUnderstandingCard } from "./dashboard";

export type MessageCategory =
  | "maintenance"
  | "payment"
  | "rent"
  | "lease"
  | "sublet"
  | "complaint"
  | "contractor_update"
  | "contractor_repairs"
  | "contractor_invoices"
  | "admin"
  | "general"
  | "other";

export type ThreadStatus = "needs_approval" | "approved" | "rejected" | "replied" | "closed";
export type SortOption = "urgency" | "latest" | "oldest";
export type AudienceFilter = "all" | "tenants" | "contractors" | "inquiries";
export type UrgencyFilter = "all" | "emergency" | "high" | "normal" | "low";

export interface ThreadMessage {
  id: string;
  sender: "tenant" | "contractor" | "owner" | "ai_assistant";
  senderName: string;
  senderContact: string; // Phone or Email
  sentAt: string;
  timeFormatted: string;
  body: string;
  bodyEnglish?: string; // cached English for a Dutch message; filled on demand by POST /api/inbox/translate
  bodyDutch?: string; // cached Dutch for an English message
  language?: "nl" | "en" | "unknown"; // from the server's language check
  channel: ChannelType;
  replyTo?: {
    id?: string;
    sender?: string;
    text?: string;
  };
  attachments?: Array<{
    name: string;
    size: string;
    type: string;
    url?: string;
  }>;
}

export interface DraftPersona {
  actingAs: string; // "Harjot"
  name: string; // persona file name shown to the owner
  version: number;
}

export interface DualChannelDrafts {
  whatsappDrafts: DraftOption[];
  gmailDrafts: DraftOption[];
}

export interface InboxThread {
  id: string;
  threadId?: string; // D4: Unified thread ID (unit + contact + ticket)
  caseRef: string;
  ticketNumber?: string; // e.g. "#3f9a1c"
  caseId?: string; // the full case id behind ticketNumber
  channel: ChannelType;
  senderKind?: string;
  recipientRole: RecipientRole;
  recipientRoleDetail: string; // e.g. "Tenant" or "Contractor · Electrician"
  contractorTrade?: string; // e.g. "Electrician", "Plumber", "HVAC"
  // Specific channel IDs
  externalMessageId: string; // e.g. "wamid.HBgL..." or "msg_18b2f90a..."
  externalThreadId?: string; // e.g. "thread_amsterdam_1092"
  approvalId?: string; // Backend approval ID for 1-click execution
  subject?: string; // For Gmail messages
  senderName: string;
  senderContact: string; // Phone "+31 6 12 34 41 87" or Email "p.bakker@..."
  isUnregisteredSender?: boolean;
  matchedTenant?: {
    id: string;
    name: string;
    unit: string;
  };
  unitLabel: string;
  buildingName: string;
  category: MessageCategory;
  urgency: UrgencyLevel;
  status: ThreadStatus;
  isRead?: boolean;
  snoozedUntil?: string | null;
  receivedAt: string; // ISO
  relativeTime: string;
  latestSnippet: string;
  issueTitle?: string; // e.g. "Washing machine is leaking"
  detectedLanguage?: string; // e.g. "Dutch (detected)"
  translatedSnippet?: string; // e.g. "Translated from Dutch: Good morning..."
  underlinedEntities?: string[];
  aiUnderstanding?: AiUnderstandingCard;
  whenYouApprove?: string[];
  caseSummary?: string; // Rolling summary from backend Case.summary
  attachments?: ThreadMessage["attachments"];
  messages: ThreadMessage[];
  inResponseToSnippet?: string; // What message the draft is answering
  draftProposal?: {
    persona?: DraftPersona; // the owner persona the drafts were written in (absent for canned drafts)
    confidence: number;
    recommendedAction: string;
    activeChannel: ChannelType;
    whatsappDrafts: DraftOption[];
    gmailDrafts: DraftOption[];
    drafts: DraftOption[]; // Active channel drafts
  };
}
