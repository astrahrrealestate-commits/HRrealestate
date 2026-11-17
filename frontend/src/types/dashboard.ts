export type ChannelType = "whatsapp" | "gmail" | "portal";

export type UrgencyLevel = "emergency" | "high" | "normal" | "low";

export type RecipientRole = "tenant" | "contractor" | "supplier" | "internal" | "inquiry";

export interface DraftOption {
  id: string;
  version: number;
  label: string; // e.g., "Draft 1 (Direct Action)"
  text: string;
  tone: "friendly" | "direct" | "formal";
  channel: ChannelType;
  recipientType: RecipientRole;
  recipientName: string;
  inResponseTo?: string; // Exact quote of the message this draft replies to
  language?: "nl" | "en" | "unknown";
  englishMeaning?: string; // cached English of a Dutch draft
  dutchMeaning?: string; // cached Dutch of an English draft
}

export interface MultiPartyDrafts {
  tenantDrafts: {
    whatsapp: DraftOption[];
    gmail: DraftOption[];
  };
  contractorDrafts?: {
    whatsapp: DraftOption[];
    gmail: DraftOption[];
  };
}

export interface UnderstandingFact {
  label: string;
  value: string;
  checked: boolean;
  isAlert?: boolean;
}

export interface AiUnderstandingCard {
  ticket: string;
  problem: string;
  unit: string;
  tenantIsHome?: string;
  priority: string;
  suggestedContractor?: string;
  customFacts?: UnderstandingFact[];
}

export interface TriageItem {
  id: string;
  caseRef: string; // e.g. "#cs-0089" or "#005"
  ticketNumber?: string; // e.g. "#005"
  channel: ChannelType;
  senderName: string;
  senderContact: string; // e.g. "+31 6 12 34 41 87" or "p.bakker@amsterdam-tech.nl"
  unitLabel: string; // e.g. "Pieter Floriszstraat 1 C"
  buildingName: string; // e.g. "Centrum Portfolio"
  category: "maintenance" | "rent" | "sublet" | "general";
  urgency: UrgencyLevel;
  slaRemainingMinutes?: number; // e.g. 42
  confidenceScore: number; // e.g. 0.93
  receivedTime: string; // e.g. "Yesterday 22:10"
  recipientRole: RecipientRole;
  recipientRoleDetail: string; // e.g. "Tenant" or "Contractor · Electrician"
  tenantMessage: string;
  issueTitle?: string; // e.g. "Washing machine is leaking"
  detectedLanguage?: string; // e.g. "Dutch (detected)"
  translatedSnippet?: string; // e.g. "Translated from Dutch: Good morning..."
  parsedSummary: string;
  recommendedAction: string;
  underlinedEntities?: string[]; // phrases to highlight like "no power in the kitchen sockets"
  aiUnderstanding?: AiUnderstandingCard;
  whenYouApprove?: string[];
  draftTranslation?: string;
  assignedContractor?: {
    name: string;
    trade: string;
    phone: string;
    email?: string;
  };
  drafts: DraftOption[];
  multiPartyDrafts?: MultiPartyDrafts;
}

export interface PulseMetrics {
  needsYouCount: number;
  emergencyCount: number;
  openRentTotalEur: number;
  overdueRentEur: number;
  overdueTenantsCount: number;
  occupancyPercentage: number;
  totalUnits: number;
  occupiedUnits: number;
  autonomousActionsWeek: number;
  hoursSavedWeek: number;
}

export interface AgingBucket {
  label: string;
  amount: number;
  percentage: number;
  colorClass: string;
  description: string;
}

export interface AutonomousActionLog {
  id: string;
  timestamp: string;
  actionText: string;
  entityRef: string;
  tag: string;
}

export type BriefingKind = "daily" | "weekly";

export interface BriefingSectionItem {
  id: string;
  badge?: string;
  badgeColor?: string;
  title: string;
  detail?: string;
  time?: string;
}

export interface BriefingSection {
  title: string;
  items: BriefingSectionItem[];
}

export interface ExecutiveBriefing {
  kind: BriefingKind;
  dayLabel: string; // e.g. "Wednesday 14 October"
  timeDelivered: string; // "07:30 CET" or "Friday 16:00 CET"
  headline: string;
  summarySentence: string;
  urgentCount: number;
  decisionsCount: number;
  overdueTasksCount: number;
  waitingCount: number;
  ignoredCount: number;
  stats?: {
    casesOpened: number;
    casesResolved: number;
    decisionsTaken: number;
    autonomousActions: number;
    collectionRate: number;
  };
  sections: BriefingSection[];
}
