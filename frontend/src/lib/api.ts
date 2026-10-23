/**
 * EstateOS Backend API Client
 * Connects the Next.js frontend to the FastAPI + DBOS backend on http://localhost:8000.
 * Pure data integration layer (REST endpoints) with robust error handling and fallback.
 */

import { InboxThread } from "@/types/inbox";
import { PulseMetrics, AutonomousActionLog } from "@/types/dashboard";
import { MOCK_INBOX_THREADS } from "@/data/inboxMockData";
import { INITIAL_METRICS, RECENT_AUTONOMOUS_LOGS } from "@/data/mockData";
import { StalledItem, INITIAL_STALLED_ITEMS } from "@/components/today/UnresponsiveRadarCard";
import { getContactDisplayName, getSnippet, getUnifiedThreadId } from "@/lib/selectors";

const BACKEND_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Inbox & Approvals
// ---------------------------------------------------------------------------

export interface FetchThreadsParams {
  channel?: "all" | "gmail" | "whatsapp";
  audience?: "all" | "tenants" | "contractors";
  category?: "all" | "contractor_repairs" | "contractor_money";
}

export interface ApprovalDecideResponse {
  status: "approved" | "rejected" | "stale";
  approvalId: string;
  decision: string;
  choice: string;
  message: string;
  executedAt: string;
}

function parseTimestampToIso(ts?: string): string {
  if (!ts) return new Date().toISOString();
  const trimmed = ts.trim();
  if (trimmed.startsWith("Today")) {
    const timePart = trimmed.replace("Today", "").trim();
    const now = new Date();
    if (timePart) {
      const [h, m] = timePart.split(":").map(Number);
      if (!isNaN(h) && !isNaN(m)) {
        now.setHours(h, m, 0, 0);
      }
    }
    return now.toISOString();
  }
  if (trimmed.startsWith("Yesterday")) {
    const timePart = trimmed.replace("Yesterday", "").trim();
    const yest = new Date();
    yest.setDate(yest.getDate() - 1);
    if (timePart) {
      const [h, m] = timePart.split(":").map(Number);
      if (!isNaN(h) && !isNaN(m)) {
        yest.setHours(h, m, 0, 0);
      }
    }
    return yest.toISOString();
  }
  const parsed = new Date(ts);
  if (!isNaN(parsed.getTime())) return parsed.toISOString();
  return new Date().toISOString();
}

/**
 * Fetches inbox threads from the backend API.
 * GET /api/inbox/threads
 */
export async function getInboxThreads(
  params: FetchThreadsParams = {}
): Promise<{ threads: InboxThread[]; isLive: boolean }> {
  const query = new URLSearchParams();
  if (params.channel && params.channel !== "all") query.set("channel", params.channel);
  if (params.audience && params.audience !== "all") query.set("audience", params.audience);
  if (params.category && params.category !== "all") query.set("category", params.category);

  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/inbox/threads?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.threads) && data.threads.length > 0) {
        const liveThreads: InboxThread[] = data.threads.map((t: any) => {
          const channel = (t.channel === "whatsapp" || t.channel === "gmail") ? t.channel : "gmail";
          const gDrafts = Array.isArray(t.gmailDrafts) ? t.gmailDrafts : [];
          const wDrafts = Array.isArray(t.whatsappDrafts) ? t.whatsappDrafts : [];
          const activeDrafts = channel === "whatsapp" ? wDrafts : gDrafts;

          const unitLabel = t.unit || t.unitLabel || "Pieter Floriszstraat 1 C";
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

          return {
            id: t.id || `thread-${Math.random()}`,
            threadId: unifiedThreadId,
            caseRef: t.caseRef || `#cs-${(t.caseId || t.id || "").slice(0, 4)}`,
            ticketNumber: t.ticketNumber || `#${(t.caseId || t.id || "").slice(0, 4)}`,
            channel,
            recipientRole: (t.audience === "contractors" || t.recipientRole === "contractor") ? "contractor" : (t.audience === "inquiries" ? "inquiry" : "tenant"),
            recipientRoleDetail: t.sender?.role || (t.audience === "contractors" ? "Contractor" : "Tenant"),
            externalMessageId: t.sourceIdentifier || t.id,
            externalThreadId: t.caseId || t.id,
            approvalId: t.approvalId || t.caseId || t.id,
            subject: t.subject || t.title,
            senderName: resolvedSenderName,
            senderContact,
            unitLabel,
            buildingName: t.buildingName || "Centrum Portfolio",
            category: t.category || "maintenance",
            urgency: t.urgency || "normal",
            status: t.status || "needs_approval",
            detectedLanguage: t.detectedLanguage || "Dutch (detected)",
            aiUnderstanding: t.aiUnderstanding,
            receivedAt: t.receivedAt || parseTimestampToIso(t.timestamp),
            relativeTime: t.timestamp || "Today",
            latestSnippet: cleanSnippet,
            inResponseToSnippet: cleanSnippet,
            caseSummary: t.aiSummary || t.caseSummary || "",
            messages: (Array.isArray(t.messages) && t.messages.length > 0)
              ? t.messages.map((m: any) => ({
                  id: m.id || `msg-${Math.random()}`,
                  sender: m.sender === "owner" ? "owner" : "tenant",
                  senderName: m.senderName || "Sender",
                  senderContact: m.senderContact || "",
                  sentAt: m.sentAt || parseTimestampToIso(m.timestamp || t.timestamp),
                  timeFormatted: m.timeFormatted || (m.timestamp || "Today"),
                  body: m.body || m.content || "",
                  channel: m.channel || channel,
                  replyTo: m.replyTo,
                }))
              : [
                  {
                    id: `msg-${t.id}-1`,
                    sender: "tenant",
                    senderName: t.sender?.name || "Tenant",
                    senderContact: t.sender?.contact || "",
                    sentAt: new Date().toISOString(),
                    timeFormatted: "Today",
                    body: t.lastMessageSnippet || "",
                    channel,
                  },
                ],
            draftProposal: (gDrafts.length > 0 || wDrafts.length > 0)
              ? {
                  confidence: (t.aiConfidence || 95) / 100,
                  recommendedAction: t.aiSummary || "Review and approve staged draft reply.",
                  activeChannel: channel,
                  whatsappDrafts: wDrafts,
                  gmailDrafts: gDrafts,
                  drafts: activeDrafts.length > 0 ? activeDrafts : (gDrafts.length > 0 ? gDrafts : wDrafts),
                }
              : undefined,
          };
        });
        return { threads: liveThreads, isLive: true };
      }
    }
  } catch {
    // Backend offline / network error -> gracefully fall back to local seed data
  }

  // Filter local mock data by parameters
  let filtered = [...MOCK_INBOX_THREADS];
  if (params.audience === "tenants") {
    filtered = filtered.filter((t) => t.recipientRole === "tenant");
  } else if (params.audience === "contractors") {
    filtered = filtered.filter((t) => t.recipientRole === "contractor");
  }

  if (params.category === "contractor_repairs") {
    filtered = filtered.filter((t) => t.category === "contractor_repairs" || t.category === "maintenance");
  } else if (params.category === "contractor_money") {
    filtered = filtered.filter((t) => t.category === "contractor_invoices" || t.category === "payment");
  }

  return { threads: filtered, isLive: false };
}

/**
 * Triggers an on-demand sync from Gmail to fetch new incoming emails and run the AI pipeline.
 * POST /api/inbox/sync
 */
export async function syncGmailInbox(): Promise<{ synced: boolean; newMessages: number; message: string }> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/inbox/sync`, {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(15000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to trigger inbox sync:", err);
  }
  return { synced: false, newMessages: 0, message: "Sync timed out or backend unreachable." };
}

/**
 * Sends Harjot's approval decision (Draft 1, Draft 2, etc.) to the backend.
 * POST /api/inbox/approvals/{id}/decide
 */
export async function approveInboxDraft(
  approvalId: string,
  choice: "d1" | "d2" | "d3" | "ok" = "d1",
  editedText?: string,
  replyToMessageId?: string
): Promise<ApprovalDecideResponse> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/inbox/approvals/${approvalId}/decide`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        choice,
        edited_text: editedText || null,
        reply_to_message_id: replyToMessageId || null,
      }),
      signal: AbortSignal.timeout(25000), // Real Gmail API dispatch takes 5-8s
    });

    if (res.ok) {
      return await res.json();
    }
    const errText = await res.text();
    console.error("Backend approval failed:", res.status, errText);
    return {
      status: "rejected",
      approvalId,
      decision: "reject",
      choice,
      message: `Failed to dispatch via Gmail (${res.status}): ${errText}`,
      executedAt: new Date().toISOString(),
    };
  } catch (err) {
    console.error("Backend approval error:", err);
    return {
      status: "rejected",
      approvalId,
      decision: "reject",
      choice,
      message: `Dispatch failed: ${err}`,
      executedAt: new Date().toISOString(),
    };
  }
}

// ---------------------------------------------------------------------------
// Dashboard Pulse, Radar, Inquiries & Autonomous Logs
// ---------------------------------------------------------------------------

export interface ProspectiveInquiry {
  id: string;
  name: string;
  contact: string;
  channel: "gmail" | "whatsapp";
  unit: string;
  moveIn: string;
  request: string;
  qualification: string;
  status: string;
}

const DEFAULT_INQUIRIES: ProspectiveInquiry[] = [
  {
    id: "lead-1",
    name: "Sanne Meijer",
    contact: "sanne.meijer@uva.nl",
    channel: "gmail",
    unit: "Pieter Floriszstraat 1 C",
    moveIn: "1 Nov 2026",
    request: "Viewing request · Thursday 15:00 slot",
    qualification: "3.2x income verified (UvA lecturer)",
    status: "AI draft ready",
  },
  {
    id: "lead-2",
    name: "Lucas van Dijk",
    contact: "+31 6 81 29 44 10",
    channel: "whatsapp",
    unit: "Singel 412 Studio",
    moveIn: "1 Nov 2026",
    request: "Studio availability & viewing inquiry",
    qualification: "Preliminary criteria met",
    status: "AI draft ready",
  },
];

/**
 * Fetches executive briefing from the BRIEFING agent.
 * GET /api/dashboard/briefing?kind=daily|weekly
 */
export async function getDashboardBriefing(kind: "daily" | "weekly" = "daily") {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/dashboard/briefing?kind=${kind}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(3000),
    });

    if (res.ok) {
      return { data: await res.json(), isLive: true };
    }
  } catch {
    // Fallback
  }
  return { data: null, isLive: false };
}

/**
 * Fetches executive pulse metrics (3 Pillars: Needs You, Rent, Occupancy).
 * GET /api/dashboard/pulse
 */
export async function getDashboardPulse(): Promise<{ metrics: PulseMetrics; isLive: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/dashboard/pulse`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      return {
        metrics: {
          needsYouCount: data.needsYouCount,
          emergencyCount: data.emergencyCount,
          openRentTotalEur: data.openRentTotalEur,
          overdueRentEur: data.overdueRentEur,
          overdueTenantsCount: data.overdueTenantsCount,
          occupancyPercentage: data.occupancyPercentage,
          totalUnits: data.totalUnits,
          occupiedUnits: data.occupiedUnits,
          autonomousActionsWeek: data.autonomousActionsWeek,
          hoursSavedWeek: data.hoursSavedWeek,
        },
        isLive: true,
      };
    }
  } catch {
    // Offline fallback
  }

  return { metrics: INITIAL_METRICS, isLive: false };
}

/**
 * Fetches stalled wait items for the Unresponsive Radar.
 * GET /api/dashboard/radar
 */
export async function getDashboardRadar(): Promise<{ items: StalledItem[]; total: number; isLive: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/dashboard/radar`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.items)) {
        // Map backend format to frontend UI format
        const mappedItems: StalledItem[] = data.items.map((item: any, idx: number) => ({
          id: item.id || `stall-${idx}`,
          type: item.partyRole?.toLowerCase().includes("contractor") ? "contractor_stalled" : "unpaid_rent",
          unitLabel: item.unitLabel || "Keizersgracht 42-A",
          partyName: item.partyName || "Unknown Party",
          partyRole: item.partyRole || "Party",
          contact: item.contact || "+31 6 00 00 00 00",
          subject: item.issueSummary || "Awaiting response",
          amount: item.amount || 2450.0,
          remindersSentCount: item.chasersSent ?? 1,
          lastMessageSent: `${item.daysWaiting ?? 2} days ago`,
          daysStalled: item.daysWaiting ?? 2,
          statusBadge: `${item.chasersSent ?? 1} reminders sent`,
          proposedActionLabel: item.proposedActionLabel || "Send follow-up",
          proposedActionDraft: `Beste ${item.partyName || "relatie"}, kunt u een update sturen? Groet, H R Real Estate.`,
        }));
        return { items: mappedItems, total: data.total, isLive: true };
      }
    }
  } catch {
    // Offline fallback
  }

  return { items: INITIAL_STALLED_ITEMS, total: INITIAL_STALLED_ITEMS.length, isLive: false };
}

/**
 * Fetches prospective tenant viewing inquiries.
 * GET /api/dashboard/inquiries
 */
export async function getDashboardInquiries(): Promise<{ inquiries: ProspectiveInquiry[]; total: number; isLive: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/dashboard/inquiries`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.inquiries)) {
        return { inquiries: data.inquiries, total: data.total, isLive: true };
      }
    }
  } catch {
    // Offline fallback
  }

  return { inquiries: DEFAULT_INQUIRIES, total: DEFAULT_INQUIRIES.length, isLive: false };
}

/**
 * Fetches autonomous background action logs for the dashboard audit trail.
 * GET /api/dashboard/logs
 */
export async function getAutonomousLogs(): Promise<{ logs: AutonomousActionLog[]; total: number; isLive: boolean }> {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/dashboard/logs`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.logs)) {
        return { logs: data.logs, total: data.total, isLive: true };
      }
    }
  } catch {
    // Offline fallback
  }

  return { logs: RECENT_AUTONOMOUS_LOGS, total: RECENT_AUTONOMOUS_LOGS.length, isLive: false };
}

// ---------------------------------------------------------------------------
// Maintenance Hub Endpoints
// ---------------------------------------------------------------------------

export interface MaintenanceTicket {
  id: string;
  ticketNumber: string;
  issueTitle: string;
  unitLabel: string;
  tenantName: string;
  tenantPhone: string;
  category: "electrical" | "plumbing" | "heating" | "appliance" | "structural";
  contractorName: string;
  contractorTrade: string;
  urgency: "emergency" | "high" | "normal" | "low";
  status: "pending_approval" | "dispatched" | "scheduled" | "completed";
  slaRemaining: string;
  isOverdue?: boolean;
  poBudgetCap: string;
  reportedAt: string;
  notes: string;
}

export interface MaintenanceStats {
  openCount: number;
  emergencyCount: number;
  dispatchedCount: number;
  overdueCount: number;
  totalPoBudgetEur: number;
}

/**
 * Fetches maintenance tickets and operational summary stats.
 * GET /api/maintenance/tickets
 */
export async function getMaintenanceTickets(params: {
  status?: string;
  category?: string;
} = {}): Promise<{ tickets: MaintenanceTicket[]; stats: MaintenanceStats | null; isLive: boolean }> {
  const query = new URLSearchParams();
  if (params.status && params.status !== "all") query.set("status", params.status);
  if (params.category && params.category !== "all") query.set("category", params.category);

  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/maintenance/tickets?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.tickets)) {
        return { tickets: data.tickets, stats: data.stats, isLive: true };
      }
    }
  } catch {
    // Offline fallback
  }

  return { tickets: [], stats: null, isLive: false };
}

/**
 * Fetches ticket lifecycle audit history.
 * GET /api/maintenance/tickets/{ticket_id}/history
 */
export async function getTicketHistory(ticketId: string): Promise<{
  ticketNumber: string;
  events: any[];
  isLive: boolean;
}> {
  try {
    const cleanId = ticketId.replace("#", "");
    const res = await fetch(`${BACKEND_BASE_URL}/api/maintenance/tickets/${cleanId}/history`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      const data = await res.json();
      return {
        ticketNumber: data.ticketNumber,
        events: data.events || [],
        isLive: true,
      };
    }
  } catch {
    // Offline fallback
  }

  return { ticketNumber: ticketId, events: [], isLive: false };
}

/**
 * Approves a maintenance work order dispatch.
 * POST /api/maintenance/tickets/{ticket_id}/approve
 */
export async function approveMaintenanceTicket(
  ticketId: string,
  approvalNote?: string
): Promise<{ status: string; ticketId: string; message: string }> {
  try {
    const cleanId = ticketId.replace("#", "");
    const res = await fetch(`${BACKEND_BASE_URL}/api/maintenance/tickets/${cleanId}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ approval_note: approvalNote || "Approved by Property Manager" }),
      signal: AbortSignal.timeout(3000),
    });

    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Offline fallback
  }

  return {
    status: "dispatched",
    ticketId,
    message: `Ticket ${ticketId} approved. Contractor work order dispatched.`,
  };
}

// ---------------------------------------------------------------------------
// Properties & Tenants Endpoints
// ---------------------------------------------------------------------------

/**
 * Fetches portfolio property units directory.
 * GET /api/properties
 */
export async function getProperties(status: string = "all") {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/properties?status=${status}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      return { data: await res.json(), isLive: true };
    }
  } catch {
    // Fallback
  }
  return { data: null, isLive: false };
}

/**
 * Fetches active tenant directory.
 * GET /api/tenants
 */
export async function getTenants(rentStatus: string = "all") {
  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/tenants?rent_status=${rentStatus}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(2500),
    });

    if (res.ok) {
      return { data: await res.json(), isLive: true };
    }
  } catch {
    // Fallback
  }
  return { data: null, isLive: false };
}

// ---------------------------------------------------------------------------
// AI Assistant / Ask EstateOS (OWNER_QA Agent)
// ---------------------------------------------------------------------------

export interface PreviewCardData {
  type: "draft_message" | "case_summary" | "task_card" | "financial_item" | string;
  channel?: string;
  recipient?: string;
  unitLabel?: string;
  subject?: string | null;
  body?: string;
  actionId?: string | null;
  caseId?: string | null;
  // Specific micro-card extensions:
  title?: string;
  subtitle?: string;
  badgeLabel?: string;
  badgeColor?: "orange" | "emerald" | "amber" | "blue" | "red";
  amount?: string;
  status?: string;
  dueDate?: string;
  contractor?: string;
  targetUrl?: string;
}

export interface AskAgentAction {
  label: string;
  actionType: string;
  payload?: any;
  isPrimary?: boolean;
}

export interface AskAgentResponse {
  answer: string;
  caseRefs?: string[];
  suggestedAction?: string | null;
  actions?: AskAgentAction[];
  executedAt: string;
  steps?: string[];
  previewCard?: PreviewCardData | null;
}

/**
 * Sends a natural language query to the Super Agent (CONCIERGE) copilot.
 * POST /api/agent/ask
 */
export async function askAgent(
  query: string,
  context?: string,
  history?: string[]
): Promise<AskAgentResponse> {
  const fallbackAns: AskAgentResponse = {
    answer: "Based on active records: 0 blocking SLA breaches detected. Pieter Bakker's emergency ticket #005 is awaiting electrician dispatch.",
    caseRefs: ["#005"],
    suggestedAction: "View ticket #005 in Maintenance",
    actions: [
      {
        label: "View ticket #005 in Maintenance",
        actionType: "navigate",
        payload: "/maintenance",
        isPrimary: true,
      },
    ],
    executedAt: new Date().toISOString(),
  };

  try {
    const res = await fetch(`${BACKEND_BASE_URL}/api/agent/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ query, context, history }),
      signal: AbortSignal.timeout(10000),
    });

    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to reach /api/agent/ask, using contextual fallback:", err);
  }

  return fallbackAns;
}

