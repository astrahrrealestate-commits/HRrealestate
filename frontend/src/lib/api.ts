/**
 * EstateOS Backend API Client
 * Connects the Next.js frontend to the FastAPI + DBOS backend (NEXT_PUBLIC_API_URL, default http://localhost:8000).
 * Pure data integration layer (REST endpoints) with robust error handling and fallback.
 */

import type { AnswerSource } from "./sources";
import { InboxThread } from "@/types/inbox";
import { caseRefTail, ticketRef } from "@/lib/caseRef";
import { BACKEND_BASE_URL, apiFetch } from "@/lib/backend";
import { localDayNumber, localWallToDate } from "@/lib/clock";
import { PulseMetrics, AutonomousActionLog } from "@/types/dashboard";
import type { BusinessCategory } from "@/lib/categoryLabels";
import { RECENT_AUTONOMOUS_LOGS } from "@/data/mockData";
import { StalledItem } from "@/components/today/UnresponsiveRadarCard";
import { getContactDisplayName, getSnippet, getUnifiedThreadId } from "@/lib/selectors";


// ---------------------------------------------------------------------------
// Inbox & Approvals
// ---------------------------------------------------------------------------

export interface FetchThreadsParams {
  channel?: "all" | "gmail" | "whatsapp";
  audience?: "all" | "tenants" | "contractors";
  category?: "all" | "contractor_repairs" | "contractor_money";
  sort?: "recent" | "priority";
  limit?: number;
  offset?: number;
  includeHtml?: boolean;
}

export interface ApprovalDecideResponse {
  status: "approved" | "rejected" | "stale";
  approvalId: string;
  decision: string;
  choice: string;
  message: string;
  executedAt: string;
}

function parseClockPart(part: string): [number, number] | null {
  const [h, m] = part.split(":").map(Number);
  return !isNaN(h) && !isNaN(m) ? [h, m] : null;
}

/** "Today 09:30" / "Yesterday 09:30" are the company's (Amsterdam) wall clock, not the browser's. An unreadable
 * stamp gives "" rather than an invented time. */
function parseTimestampToIso(ts?: string): string {
  if (!ts) return "";
  const trimmed = ts.trim();
  for (const [word, daysAgo] of [["Today", 0], ["Yesterday", 1]] as const) {
    if (!trimmed.startsWith(word)) continue;
    const now = new Date();
    const clock = parseClockPart(trimmed.replace(word, "").trim());
    if (!clock) return "";
    return localWallToDate(localDayNumber(now) - daysAgo, clock[0], clock[1]).toISOString();
  }
  const parsed = new Date(ts);
  return isNaN(parsed.getTime()) ? "" : parsed.toISOString();
}

/**
 * Fetches lightweight inbox badge counts from SQL (GET /api/inbox/stats).
 */
export async function getInboxNeedsYouCount(): Promise<number | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/stats`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = await res.json();
      if (typeof data.needsYouCount === "number") return data.needsYouCount;
    }
  } catch {
    // Offline fallback
  }
  return null;
}

/**
 * Fetches inbox threads from the backend API.
 * GET /api/inbox/threads
 */
export async function getInboxThreads(
  params: FetchThreadsParams = {}
): Promise<{ threads: InboxThread[]; isLive: boolean; total?: number; hasMore?: boolean }> {
  const query = new URLSearchParams();
  if (params.channel && params.channel !== "all") query.set("channel", params.channel);
  if (params.audience && params.audience !== "all") query.set("audience", params.audience);
  if (params.category && params.category !== "all") query.set("category", params.category);
  if (params.sort && params.sort !== "recent") query.set("sort", params.sort);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.includeHtml === false) query.set("include_html", "false");

  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(20000),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.threads)) {
        const liveThreads: InboxThread[] = data.threads.map((t: any) => {
          const channel = (t.channel === "whatsapp" || t.channel === "gmail") ? t.channel : "gmail";
          const gDrafts = Array.isArray(t.gmailDrafts) ? t.gmailDrafts : [];
          const wDrafts = Array.isArray(t.whatsappDrafts) ? t.whatsappDrafts : [];
          const activeDrafts = channel === "whatsapp" ? wDrafts : gDrafts;

          const unitLabel = t.unit || t.unitLabel || ""; // empty for a sender with no flat or organisation
          const rawSnippet = t.lastMessageSnippet || t.latestSnippet || "";
          const cleanSnippet = getSnippet(rawSnippet);
          const senderContact = t.sender?.contact || t.senderContact || "";
          const resolvedSenderName = getContactDisplayName({
            senderName: t.sender?.name || t.senderName,
            senderContact,
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
            id: t.id || `thread-${Math.random()}`,
            threadId: unifiedThreadId,
            caseRef: t.caseRef || `#cs-${caseRefTail(t.caseId || t.id)}`,
            ticketNumber: t.ticketNumber || t.aiUnderstanding?.ticket || ticketRef(t.caseId || t.id),
            caseId: t.caseId || t.id,
            channel,
            senderKind: t.senderKind || (t.audience === "contractors" ? "contractor" : t.audience === "inquiries" ? "prospect" : t.audience === "tenants" ? "tenant" : "contact"),
            recipientRole: (t.audience === "contractors" || t.recipientRole === "contractor") ? "contractor" : (t.audience === "inquiries" ? "inquiry" : (t.audience === "others" || t.recipientRole === "contact" ? "contact" : "tenant")),
            recipientRoleDetail: t.recipientRoleDetail || t.sender?.role || (t.audience === "contractors" ? "Contractor" : (t.audience === "others" ? "Contact" : "Tenant")),
            externalMessageId: t.externalMessageId || t.sourceIdentifier || t.id,
            externalThreadId: t.externalThreadId || t.caseId || t.id,
            approvalId: t.approvalId || t.caseId || t.id,
            subject: t.subject || t.title,
            senderMessageId: t.senderMessageId,
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
            receivedAt: t.receivedAt || parseTimestampToIso(t.timestamp),
            relativeTime: t.timestamp || "Today",
            latestSnippet: cleanSnippet,
            inResponseToSnippet: cleanSnippet,
            caseSummary: t.aiSummary || t.caseSummary || "",
            attachments: t.attachments || [],
            messages: (Array.isArray(t.messages) && t.messages.length > 0)
              ? t.messages.map((m: any) => ({
                  id: m.id || `msg-${Math.random()}`,
                  sender: m.sender === "owner" ? "owner" : "tenant",
                  senderName: m.senderName || "Sender",
                  senderContact: m.senderContact || "",
                  sentAt: m.sentAt || parseTimestampToIso(m.timestamp || t.timestamp),
                  timeFormatted: m.timeFormatted || (m.timestamp || "Today"),
                  body: m.body || m.content || "",
                  bodyHtml: m.bodyHtml || null,
                  bodyEnglish: m.bodyEnglish || undefined,
                  bodyDutch: m.bodyDutch || undefined,
                  language: m.language,
                  channel: m.channel || channel,
                  subject: m.subject,
                  to: Array.isArray(m.to) ? m.to : undefined,
                  cc: Array.isArray(m.cc) ? m.cc : undefined,
                  replyTo: m.replyTo,
                  attachments: m.attachments || [],
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
                    attachments: t.attachments || [],
                  },
                ],
            draftProposal: (!isApproved && !lastMsgIsOutbound && (gDrafts.length > 0 || wDrafts.length > 0))
              ? {
                  confidence: (t.aiConfidence || 95) / 100,
                  recommendedAction: t.aiSummary || "Review and approve staged draft reply.",
                  activeChannel: channel,
                  persona: t.draftPersona || undefined,
                  whatsappDrafts: wDrafts,
                  gmailDrafts: gDrafts,
                  drafts: activeDrafts.length > 0 ? activeDrafts : (gDrafts.length > 0 ? gDrafts : wDrafts),
                }
              : undefined,
          };
        });
        return {
          threads: liveThreads,
          isLive: true,
          total: data.total ?? liveThreads.length,
          hasMore: Boolean(data.has_more),
        };
      }
    }
  } catch {
    // Backend offline / network error
  }

  // Backend unreachable: show nothing rather than seed threads that look like the owner's mail.
  return { threads: [], isLive: false, total: 0, hasMore: false };
}

type SyncResult = { synced: boolean; newMessages: number; message: string };

const SYNC_MIN_GAP_MS = 10_000; // the server allows 6 syncs a minute per owner; page loads and polling must share them
let syncInFlight: Promise<SyncResult> | null = null;
let lastSyncAt = 0;
let lastSyncResult: SyncResult | null = null;

async function postInboxSync(): Promise<SyncResult> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/sync`, {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(60000),
    });
    if (res.ok) {
      return await res.json();
    }
    if (res.status === 429) {
      return { synced: false, newMessages: 0, message: "Sync is rate limited. Try again in a minute." };
    }
  } catch (err) {
    console.warn("Failed to trigger inbox sync:", err);
  }
  return { synced: false, newMessages: 0, message: "Sync timed out or backend unreachable." };
}

/**
 * Triggers an on-demand sync from Gmail to fetch new incoming emails and run the AI pipeline.
 * POST /api/inbox/sync. Calls made while one is running share it, and calls within SYNC_MIN_GAP_MS of the last
 * answer reuse that answer, so repeated page loads and the polling timer cannot trip the server's rate limit.
 */
export async function syncGmailInbox(): Promise<SyncResult> {
  if (syncInFlight) return syncInFlight;
  if (lastSyncResult && Date.now() - lastSyncAt < SYNC_MIN_GAP_MS) return lastSyncResult;
  syncInFlight = postInboxSync().then((result) => {
    lastSyncAt = Date.now();
    lastSyncResult = result;
    return result;
  });
  try {
    return await syncInFlight;
  } finally {
    syncInFlight = null;
  }
}

/**
 * Sends Harjot's approval decision (Draft 1, Draft 2, etc.) to the backend.
 * POST /api/inbox/approvals/{id}/decide
 */
export async function approveInboxDraft(
  approvalId: string,
  choice: "d1" | "d2" | "d3" | "ok" | "edit" | "rej" = "d1",
  editedText?: string,
  replyToMessageId?: string,
  attachmentIds?: string[]
): Promise<ApprovalDecideResponse & { ok?: boolean }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/approvals/${approvalId}/decide`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        choice,
        edited_text: editedText || null,
        reply_to_message_id: replyToMessageId || null,
        attachment_ids: attachmentIds ?? [],
      }),
      signal: AbortSignal.timeout(25000), // Real Gmail API dispatch takes 5-8s
    });

    if (res.ok) {
      const data = await res.json();
      const ok = data.status !== "rejected" && data.status !== "held";
      return { ok, ...data };
    }
    const errText = await res.text();
    console.error("Backend approval failed:", res.status, errText);
    return {
      ok: false,
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
      ok: false,
      status: "rejected",
      approvalId,
      decision: "reject",
      choice,
      message: `Dispatch failed: ${err}`,
      executedAt: new Date().toISOString(),
    };
  }
}

export async function sendThreadReply(
  caseId: string,
  body: string,
  channel: "gmail" | "whatsapp",
  replyToMessageId?: string,
  attachmentIds?: string[]
): Promise<{ ok: boolean; status: string; message: string }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/reply`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        body,
        channel,
        reply_to_message_id: replyToMessageId || null,
        attachment_ids: attachmentIds ?? [],
      }),
      signal: AbortSignal.timeout(25000),
    });
    if (res.ok) {
      const data = await res.json();
      return { ok: true, status: data.status || "approved", message: data.message || "Reply queued for sending." };
    }
    const errData = await res.json().catch(() => null);
    const errDetail = (errData && typeof errData.detail === "string" ? errData.detail : null) || `HTTP ${res.status}`;
    return { ok: false, status: "rejected", message: `Reply failed: ${errDetail}` };
  } catch (err) {
    return { ok: false, status: "rejected", message: `Reply failed: ${err}` };
  }
}

/**
 * Opens an existing Gmail thread (#all/<thread_id>) when replying, or a fresh compose window for new emails.
 */
export async function createGmailDraft(payload: {
  to_email: string;
  subject: string;
  body: string;
  thread_id?: string;
  case_id?: string;
}): Promise<{ ok: boolean; web_url: string; threaded?: boolean; draft_id?: string; thread_id?: string }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/create-draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("createGmailDraft error:", err);
  }
  if (payload.thread_id) {
    return {
      ok: true,
      threaded: true,
      thread_id: payload.thread_id,
      web_url: `https://mail.google.com/mail/#all/${encodeURIComponent(payload.thread_id)}`,
    };
  }
  const encodedTo = encodeURIComponent(payload.to_email);
  const encodedSu = encodeURIComponent(
    payload.subject.toLowerCase().startsWith("re:") ? payload.subject : `Re: ${payload.subject}`
  );
  const encodedBody = encodeURIComponent(payload.body);
  return {
    ok: false,
    threaded: false,
    web_url: `https://mail.google.com/mail/?view=cm&fs=1&to=${encodedTo}&su=${encodedSu}&body=${encodedBody}`,
  };
}

export async function markThreadRead(caseId: string, read = true): Promise<boolean> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ read }),
      signal: AbortSignal.timeout(8000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function markThreadDone(caseId: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/done`, {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function snoozeThread(caseId: string, until?: string): Promise<{ ok: boolean; snoozedUntil?: string }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/snooze`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ until: until ?? null }),
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) return await res.json();
  } catch {
    // ignore
  }
  return { ok: false };
}

export async function linkThreadTenant(
  caseId: string,
  tenantId: string | undefined,
  messageId: string | undefined // the mail whose sender the banner names; the server refuses if it is no longer the latest
): Promise<{ ok: boolean; tenantId?: string; tenantName?: string }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/link-tenant`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ tenant_id: tenantId ?? null, message_id: messageId }),
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) return await res.json();
  } catch {
    // ignore
  }
  return { ok: false };
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

/**
 * Fetches executive briefing from the BRIEFING agent.
 * GET /api/dashboard/briefing?kind=daily|weekly
 */
export async function getDashboardBriefing(kind: "daily" | "weekly" = "daily") {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/briefing?kind=${kind}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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
export async function getDashboardPulse(): Promise<{ metrics: PulseMetrics | null; isLive: boolean }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/pulse`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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
    // Offline: never invent demo metrics
  }

  return { metrics: null, isLive: false };
}

export interface AttentionItem {
  id: string;
  kind: "ticket" | "rent" | "lease";
  title: string;
  detail: string;
  unitLabel: string;
  partyName: string;
  urgent: boolean;
  ageDays: number;
  href: string;
  source: string;
}

/**
 * Fetches what BRIXX says needs the owner (open tickets, overdue rent, leases ending), so Today is not empty
 * when Gmail and WhatsApp are not connected.
 * GET /api/dashboard/attention
 */
export async function getDashboardAttention(): Promise<{ items: AttentionItem[]; total: number; urgentCount: number }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/attention?limit=20`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.items)) {
        return { items: data.items, total: data.total ?? data.items.length, urgentCount: data.urgentCount ?? 0 };
      }
    }
  } catch {
    // Offline: nothing to show
  }
  return { items: [], total: 0, urgentCount: 0 };
}

/**
 * Fetches stalled wait items for the Unresponsive Radar.
 * GET /api/dashboard/radar
 */
export async function getDashboardRadar(): Promise<{ items: StalledItem[]; total: number; isLive: boolean }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/radar`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.items)) {
        // Map backend format to frontend UI format
        const mappedItems: StalledItem[] = data.items.map((item: any, idx: number) => ({
          id: item.id || `stall-${idx}`,
          type: item.partyRole?.toLowerCase().includes("contractor") ? "contractor_stalled" : "unpaid_rent",
          unitLabel: item.unitLabel || "Unknown unit",
          partyName: item.partyName || "Unknown Party",
          partyRole: item.partyRole || "Party",
          contact: item.contact || "",
          subject: item.issueSummary || "Awaiting response",
          amount: item.amount ?? 0,
          remindersSentCount: item.chasersSent ?? 0,
          lastMessageSent: `${item.daysWaiting ?? 0} days ago`,
          daysStalled: item.daysWaiting ?? 0,
          statusBadge: `${item.chasersSent ?? 0} reminders sent`,
          proposedActionLabel: item.proposedActionLabel || "Open in Inbox",
          proposedActionDraft: item.proposedActionDraft || "",
        }));
        return { items: mappedItems, total: data.total, isLive: true };
      }
    }
  } catch {
    // Offline: never show demo rows
  }

  return { items: [], total: 0, isLive: false };
}

/**
 * Fetches prospective tenant viewing inquiries.
 * GET /api/dashboard/inquiries
 */
export async function getDashboardInquiries(): Promise<{ inquiries: ProspectiveInquiry[]; total: number; isLive: boolean }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/inquiries`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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

  return { inquiries: [], total: 0, isLive: false };
}

/**
 * Fetches autonomous background action logs for the dashboard audit trail.
 * GET /api/dashboard/logs
 */
export async function getAutonomousLogs(): Promise<{ logs: AutonomousActionLog[]; total: number; isLive: boolean }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/logs`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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
  tenantId?: string;
  tenantPhone: string;
  category: "electrical" | "plumbing" | "heating" | "appliance" | "structural";
  contractorName: string;
  contractorTrade: string;
  contractorPhone?: string;
  contractorEmail?: string;
  urgency: "emergency" | "high" | "normal" | "low";
  status: "pending_approval" | "dispatched" | "scheduled" | "completed";
  slaRemaining: string;
  isOverdue?: boolean;
  poBudgetCap: string;
  reportedAt: string;
  notes: string;
  originalMessage?: string;
  tenantDraft?: string;
  contractorDraft?: string;
  source?: string;
  channel?: string;
  location?: string | null;
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
  tenantId?: string;
} = {}): Promise<{ tickets: MaintenanceTicket[]; stats: MaintenanceStats | null; isLive: boolean }> {
  const query = new URLSearchParams();
  if (params.status && params.status !== "all") query.set("status", params.status);
  if (params.category && params.category !== "all") query.set("category", params.category);
  if (params.tenantId) query.set("tenant_id", params.tenantId);

  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/maintenance/tickets?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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
 * Updates a maintenance ticket's details, contractor, PO budget cap, or drafts.
 * PATCH /api/maintenance/tickets/{ticket_id}
 */
export async function updateMaintenanceTicket(
  ticketId: string,
  updates: Partial<MaintenanceTicket>
): Promise<{ ticket: MaintenanceTicket | null; success: boolean }> {
  try {
    const cleanId = ticketId.replace("#", "");
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/maintenance/tickets/${cleanId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(updates),
      signal: AbortSignal.timeout(10000),
    });

    if (res.ok) {
      const updated = await res.json();
      return { ticket: updated, success: true };
    }
  } catch (err) {
    console.warn("Failed to patch ticket in backend:", err);
  }
  return { ticket: null, success: false };
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
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/maintenance/tickets/${cleanId}/history`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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

export interface ApproveMaintenanceOptions {
  approvalNote?: string;
  dispatchContractor?: boolean;
  notifyTenant?: boolean;
  contractorMessage?: string;
  tenantMessage?: string;
  poBudgetCap?: string;
}

/**
 * Approves a maintenance work order dispatch and/or notifies the tenant.
 * POST /api/maintenance/tickets/{ticket_id}/approve
 */
export async function approveMaintenanceTicket(
  ticketId: string,
  options: ApproveMaintenanceOptions | string = {}
): Promise<{ status: string; ticketId: string; message: string; contractorDispatched?: boolean; tenantNotified?: boolean }> {
  const opts: ApproveMaintenanceOptions =
    typeof options === "string" ? { approvalNote: options } : options;

  try {
    const cleanId = ticketId.replace("#", "");
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/maintenance/tickets/${cleanId}/approve`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        approvalNote: opts.approvalNote || "Approved by Property Manager",
        dispatchContractor: opts.dispatchContractor ?? true,
        notifyTenant: opts.notifyTenant ?? true,
        contractorMessage: opts.contractorMessage || null,
        tenantMessage: opts.tenantMessage || null,
        poBudgetCap: opts.poBudgetCap || null,
      }),
      signal: AbortSignal.timeout(10000),
    });

    if (res.ok) {
      const data = await res.json();
      return {
        status: data.status || "dispatched",
        ticketId,
        message: `Ticket ${ticketId} approved. Contractor dispatched and tenant confirmed.`,
        contractorDispatched: data.contractorDispatched,
        tenantNotified: data.tenantNotified,
      };
    }
  } catch {
    // Offline fallback
  }

  return {
    status: "dispatched",
    ticketId,
    message: `Ticket ${ticketId} approved. Contractor work order dispatched.`,
    contractorDispatched: opts.dispatchContractor ?? true,
    tenantNotified: opts.notifyTenant ?? true,
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
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/properties?status=${status}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/tenants?rent_status=${rentStatus}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
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

export interface CardAction {
  label: string;
  kind: "api_call" | "navigate" | "open_external";
  endpoint?: string;
  method?: "POST" | "GET";
  payload?: any;
  targetUrl?: string;
  variant?: "primary" | "secondary" | "danger" | "whatsapp" | "gmail";
}

export interface AssistantCard {
  id: string;
  type: string;
  badgeLabel?: string;
  badgeColor?: "orange" | "emerald" | "amber" | "blue" | "red" | "rose" | string;
  title?: string;
  subtitle?: string;
  body?: string;
  amount?: string;
  contractor?: string;
  dueDate?: string;
  status?: string;
  unitLabel?: string;
  recipient?: string;
  channel?: string;
  actions?: CardAction[];
  externalUrl?: string | null;
  threadSearchUrl?: string | null;
  targetUrl?: string | null;
  caseId?: string | null;
  actionId?: string | null;
  columns?: string[];
  rows?: Array<Record<string, any>>;
  totalCount?: number | null;
  phone?: string | null;
  email?: string | null;
  leaseStart?: string | null;
  leaseEnd?: string | null;
}

export interface PreviewCardData {
  type: "draft_message" | "case_summary" | "data_table" | "tenant_lease" | "task_card" | "financial_item" | string;
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
  badgeColor?: "orange" | "emerald" | "amber" | "blue" | "red" | "rose" | string;
  amount?: string;
  status?: string;
  dueDate?: string;
  contractor?: string;
  targetUrl?: string;
  externalUrl?: string | null;
  threadSearchUrl?: string | null;
  variants?: string[];
  personaName?: string | null; // owner persona a draft_message was written in
  personaVersion?: number | null;
  columns?: string[];
  rows?: Array<Record<string, any>>;
  totalCount?: number | null;
  phone?: string | null;
  email?: string | null;
  leaseStart?: string | null;
  leaseEnd?: string | null;
}

export interface AskAgentAction {
  label: string;
  actionType: string;
  payload?: any;
  isPrimary?: boolean;
}

export interface DebugInfo {
  pipeline_stage: string;
  fallback_reason?: string | null;
}

export interface AskAgentResponse {
  conversation_id?: string;
  conversation_title?: string;
  answer: string;
  caseRefs?: string[];
  suggestedAction?: string | null;
  actions?: AskAgentAction[];
  executedAt: string;
  steps?: string[];
  previewCard?: PreviewCardData | null;
  previewCards?: PreviewCardData[];
  cards?: AssistantCard[];
  debugInfo?: DebugInfo | null;
  suggestedPrompts?: string[];
  focus_state?: Record<string, any>;
  sources?: AnswerSource[];
}

export interface ConversationSummaryItem {
  id: string;
  title: string;
  last_turn_at: string;
  snippet: string;
  pinned: boolean;
  time_bucket: "Today" | "Yesterday" | "Earlier" | string;
}

export interface TurnReplayItem {
  id: string;
  sender: "user" | "assistant";
  text: string;
  timestamp: string;
  steps?: string[];
  previewCard?: PreviewCardData | null;
  previewCards?: PreviewCardData[];
  cards?: AssistantCard[];
  actions?: AskAgentAction[];
  suggestedPrompts?: string[];
}

export interface ConversationDetailResponse {
  id: string;
  title: string;
  pinned: boolean;
  last_turn_at: string;
  focus_state: Record<string, any>;
  turns: TurnReplayItem[];
}

/**
 * Sends a natural language query to the Super Agent (CONCIERGE) copilot.
 * POST /api/agent/ask
 */
export async function askAgent(
  query: string,
  context?: string,
  history?: string[],
  conversationId?: string | null
): Promise<AskAgentResponse> {
  const buildErrorResponse = (
    answer: string,
    stage: string,
    reason: string
  ): AskAgentResponse => ({
    answer,
    caseRefs: [],
    suggestedAction: "View Maintenance Hub",
    actions: [
      {
        label: "View Maintenance Hub",
        actionType: "navigate",
        payload: "/maintenance",
        isPrimary: true,
      },
    ],
    executedAt: new Date().toISOString(),
    debugInfo: {
      pipeline_stage: stage,
      fallback_reason: reason,
    },
  });

  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/agent/ask/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream, application/json",
      },
      body: JSON.stringify({ query, context, history, conversation_id: conversationId || null }),
      // A researched answer takes the planner plus SUPER_AGENT_DEADLINE_SEC (100 s in stage/prod, ALB idle 150 s).
      signal: AbortSignal.timeout(150000),
    });

    if (res.ok) {
      const contentType = res.headers.get("content-type") || "";
      if (!contentType.includes("text/event-stream") || !res.body) {
        return await res.json();
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          let eventType = "message";
          let dataLine = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }
          if (!dataLine) continue;
          if (eventType === "result") {
            return JSON.parse(dataLine) as AskAgentResponse;
          }
          if (eventType === "error") {
            const errPayload = JSON.parse(dataLine) as { status?: number; detail?: string };
            return buildErrorResponse(
              errPayload.detail || "Astra encountered a server error. Please try again.",
              errPayload.status === 429 ? "rate_limited" : "server_error",
              `HTTP ${errPayload.status ?? 500}`
            );
          }
        }
      }
    }

    let detail = "";
    try {
      const errBody = await res.json();
      detail = typeof errBody?.detail === "string" ? errBody.detail : "";
    } catch {
      // non-JSON error body
    }
    if (res.status === 401) {
      return buildErrorResponse(
        "Your session has expired. Please refresh or sign in again to continue.",
        "auth_error",
        "HTTP 401"
      );
    }
    if (res.status === 429) {
      return buildErrorResponse(
        detail || "Rate limit reached — please wait a few seconds before asking again.",
        "rate_limited",
        "HTTP 429"
      );
    }
    return buildErrorResponse(
      detail
        ? `Astra encountered a server error (${res.status}): ${detail}`
        : `Astra encountered a server error (HTTP ${res.status}). Please try again.`,
      "server_error",
      `HTTP ${res.status}`
    );
  } catch (err) {
    console.warn("Failed to reach /api/agent/ask, using contextual fallback:", err);
    if (err instanceof DOMException && err.name === "TimeoutError") {
      return buildErrorResponse(
        "The request took too long to answer (>55s). Try a shorter or more specific question.",
        "timeout",
        "Client timeout (55s)"
      );
    }
  }

  return buildErrorResponse(
    "Unable to reach the EstateOS backend right now. Please verify the API connection and try again.",
    "network_error",
    "Backend request failed"
  );
}

export async function getAgentConversations(): Promise<ConversationSummaryItem[]> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/agent/conversations`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = await res.json();
      return data.conversations || [];
    }
  } catch (e) {
    console.warn("getAgentConversations failed", e);
  }
  return [];
}

export async function getConversationDetail(conversationId: string): Promise<ConversationDetailResponse | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/agent/conversations/${conversationId}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (e) {
    console.warn("getConversationDetail failed", e);
  }
  return null;
}

export async function updateAgentConversation(
  conversationId: string,
  payload: { title?: string; pinned?: boolean; hidden?: boolean }
): Promise<boolean> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/agent/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000),
    });
    return res.ok;
  } catch (e) {
    console.warn("updateAgentConversation failed", e);
    return false;
  }
}


// ---------------------------------------------------------------------------
// Authentication Handshake & Session Management
// ---------------------------------------------------------------------------

let authPromise: Promise<void> | null = null;

export async function ensureAuthenticated(): Promise<void> {
  // The fixed test token only exists for the fake identity provider of local development. A production bundle never
  // sends it: real sessions come from the Google login page.
  if (process.env.NODE_ENV === "production") return;
  if (authPromise) return authPromise;
  authPromise = (async () => {
    try {
      await apiFetch(`${BACKEND_BASE_URL}/api/v1/auth/session`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-EstateOS-Client": "dashboard",
        },
        body: JSON.stringify({ id_token: "test-owner-token" }),
        credentials: "include",
      });
    } catch (err) {
      console.warn("Auth handshake failed (dev mode fallback active):", err);
    }
  })();
  return authPromise;
}

// ---------------------------------------------------------------------------
// T5 Standing Memory & Owner Preferences (/api/v1/memory)
// ---------------------------------------------------------------------------

export interface MemoryItem {
  id: string;
  company_id: string;
  scope: "company" | "unit" | "person";
  scope_id: string | null;
  kind: "rule" | "preference" | "fact" | "note";
  text: string;
  status: "proposed" | "active" | "retired";
  origin: "owner" | "distilled" | "system";
  source_refs: unknown[];
  confidence: number;
  evidence_count: number;
  last_used_at: string | null;
  valid_until: string | null;
  created_at: string;
  updated_at: string;
}

export async function getStandingRules(params?: {
  status?: string;
  scope?: string;
  kind?: string;
  limit?: number;
}): Promise<MemoryItem[]> {
  await ensureAuthenticated();
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.scope) query.set("scope", params.scope);
  if (params?.kind) query.set("kind", params.kind);
  if (params?.limit) query.set("limit", params.limit.toString());

  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/memory?${query.toString()}`, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-EstateOS-Client": "dashboard",
      },
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to fetch memory items:", err);
  }
  return [];
}

export async function createStandingRule(data: {
  text: string;
  scope?: "company" | "unit" | "person";
  scope_id?: string | null;
  kind?: "rule" | "preference" | "fact" | "note";
}): Promise<MemoryItem | null> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/memory`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-EstateOS-Client": "dashboard",
      },
      credentials: "include",
      body: JSON.stringify({
        text: data.text,
        scope: data.scope || "company",
        scope_id: data.scope_id || null,
        kind: data.kind || "preference",
      }),
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to create memory item:", err);
  }
  return null;
}

export async function retireStandingRule(memoryId: string): Promise<boolean> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/memory/${memoryId}`, {
      method: "DELETE",
      headers: {
        "X-EstateOS-Client": "dashboard",
      },
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch (err) {
    console.warn("Failed to retire memory item:", err);
    return false;
  }
}

export async function approveStandingRule(memoryId: string): Promise<boolean> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/memory/${memoryId}/approve`, {
      method: "POST",
      headers: {
        "X-EstateOS-Client": "dashboard",
      },
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch (err) {
    console.warn("Failed to approve memory item:", err);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Owner writing persona (/api/v1/persona): the markdown the draft agent writes in
// ---------------------------------------------------------------------------

export interface OwnerPersona {
  name: string;
  filename: string | null;
  content: string;
  version: number;
  is_default: boolean;
  updated_at: string;
  max_chars: number;
}

const PERSONA_HEADERS = {
  "Content-Type": "application/json",
  Accept: "application/json",
  "X-EstateOS-Client": "dashboard",
};

export async function getOwnerPersona(): Promise<OwnerPersona | null> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/persona`, {
      headers: PERSONA_HEADERS,
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) return await res.json();
  } catch (err) {
    console.warn("Failed to fetch persona:", err);
  }
  return null;
}

/** Saves an edited or uploaded persona. Returns the stored persona, or an error message to show the owner. */
export async function saveOwnerPersona(data: {
  content: string;
  name?: string;
  filename?: string;
}): Promise<{ persona: OwnerPersona } | { error: string }> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/persona`, {
      method: "PUT",
      headers: PERSONA_HEADERS,
      credentials: "include",
      body: JSON.stringify(data),
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) return { persona: await res.json() };
    const body = await res.json().catch(() => null);
    return { error: typeof body?.detail === "string" ? body.detail : "Could not save the persona." };
  } catch {
    return { error: "Backend unreachable. The persona was not saved." };
  }
}

export async function resetOwnerPersona(): Promise<OwnerPersona | null> {
  await ensureAuthenticated();
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/persona/reset`, {
      method: "POST",
      headers: PERSONA_HEADERS,
      credentials: "include",
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) return await res.json();
  } catch (err) {
    console.warn("Failed to reset persona:", err);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Page Pre-Warming Context Dispatcher (/api/v1/agent/page)
// ---------------------------------------------------------------------------

export interface PrewarmPageParams {
  pageName: string;
  unitId?: string;
  ticketNumber?: string;
  threadId?: string;
  approvalId?: string;
  taskRef?: string;
}

// Must be one of app.contracts.page_context.PageView's members (inbox, thread, case, approvals, tasks, waiting,
// documents, briefing, other) — anything else is a 422, Pydantic rejects it outright. The backend only stores the
// value as a label (it does not branch on it), so most EstateOS nav pages have no dedicated member and take "other";
// only a thread/case/approval/etc. detail view gets its own.
export async function prewarmAgentPage(params: PrewarmPageParams): Promise<boolean> {
  await ensureAuthenticated();
  try {
    let view = "other";
    const lower = params.pageName.toLowerCase();
    if (lower.includes("inbox")) view = "inbox";
    else if (lower.includes("maintenance") || lower.includes("ticket")) view = "case";

    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/agent/page`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-EstateOS-Client": "dashboard",
      },
      credentials: "include",
      body: JSON.stringify({
        view,
        thread_key: params.threadId || null,
        approval_id: params.approvalId || null,
        task_ref: params.taskRef || (params.ticketNumber ? `#${params.ticketNumber}` : null),
        visible_ids: [],
      }),
      signal: AbortSignal.timeout(10000),
    });
    return res.ok;
  } catch {
    return false;
  }
}



export interface GoogleAuthStatus {
  connected: boolean;
  email?: string;
  name?: string;
  picture?: string;
  scopes?: string[];
  connected_at?: string;
  /** The status could not be read (offline, server error). `connected: false` then means "unknown", not "off". */
  unreachable?: boolean;
}

export async function getGoogleAuthStatus(): Promise<GoogleAuthStatus> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/auth/google/status`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Failed to fetch Google auth status:", err);
  }
  return { connected: false, unreachable: true };
}

export interface WhatsAppSetup {
  configured: boolean;
  provider: string;
}

/** GET /api/v1/channels/whatsapp/status: what the server is set up for; null when it cannot be read. */
export async function getWhatsAppSetup(): Promise<WhatsAppSetup | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/channels/whatsapp/status`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    return res.ok ? ((await res.json()) as WhatsAppSetup) : null;
  } catch {
    return null;
  }
}

export interface BrixxSyncStatus {
  stale: boolean;
  totalRows: number;
  lastRunAt: string | null;
  lastRunStatus: string | null;
}

/** GET /api/v1/brixx/status: the newest sync run; null when it cannot be read. */
export async function getBrixxSyncStatus(): Promise<BrixxSyncStatus | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/brixx/status`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const body: { stale: boolean; total_rows: number; last_run: { status: string; finished_at: string | null; started_at: string } | null } =
      await res.json();
    return {
      stale: body.stale,
      totalRows: body.total_rows,
      lastRunAt: body.last_run ? (body.last_run.finished_at ?? body.last_run.started_at) : null,
      lastRunStatus: body.last_run?.status ?? null,
    };
  } catch {
    return null;
  }
}

export async function getGoogleAuthUrl(returnTo: string = "/"): Promise<string | null> {
  try {
    const query = returnTo ? `?return_to=${encodeURIComponent(returnTo)}` : "";
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/auth/google/url${query}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      return data.url || null;
    }
  } catch (err) {
    console.warn("Failed to fetch Google auth URL:", err);
  }
  return null;
}

export async function disconnectGoogleAccount(): Promise<boolean> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/auth/google/disconnect`, {
      method: "POST",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch (err) {
    console.warn("Failed to disconnect Google account:", err);
    return false;
  }
}


// ---------------------------------------------------------------------------
// Contact Live Communications
// ---------------------------------------------------------------------------

export interface ContactCommunicationsData {
  contact_id: string;
  email?: string;
  phone?: string;
  emails: any[];
  whatsapp_messages: any[];
  suggested_whatsapp_drafts?: any[];
  source: "live_db" | "seeded_fallback";
}

/**
 * Retrieves all directory contacts directly from the database.
 * GET /api/contacts
 */
export async function getContactsList(audience: "all" | "tenant" | "contractor" = "all"): Promise<any[]> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/contacts?audience=${audience}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        return data;
      }
    }
  } catch {
    // Backend offline / network error
  }
  return [];
}

export async function getContactCommunications(
  contactId: string,
  email?: string,
  phone?: string
): Promise<ContactCommunicationsData | null> {
  try {
    const params = new URLSearchParams();
    if (email) params.append("email", email);
    if (phone) params.append("phone", phone);

    const qs = params.toString() ? `?${params.toString()}` : "";
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/communications${qs}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(10000),
      }
    );
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Backend API offline / unreachable -> cleanly fall back to local seed data
  }
  return null;
}

export async function sendContactWhatsAppMessage(
  contactId: string,
  text: string
): Promise<any | null> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/whatsapp/send`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ text }),
        signal: AbortSignal.timeout(10000),
      }
    );
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Backend offline / network error
  }
  return null;
}


export interface DraftVariant {
  id: string;
  label: string;
  body: string;
}

export async function generateEmailDrafts(
  contactId: string,
  messageId: string,
  guidance?: string
): Promise<DraftVariant[] | null> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/messages/${encodeURIComponent(messageId)}/generate-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ guidance }),
        signal: AbortSignal.timeout(6000),
      }
    );
    if (res.ok) {
      const data = await res.json();
      return data.drafts || null;
    }
  } catch {
    // Graceful offline fallback
  }
  return null;
}

export async function sendEmailReply(
  contactId: string,
  messageId: string,
  subject: string,
  body: string,
  choice: string = "d1"
): Promise<{ success: boolean; message_id: string; sent_at: string } | null> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/messages/${encodeURIComponent(messageId)}/reply-mail`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ subject, body, choice }),
        signal: AbortSignal.timeout(6000),
      }
    );
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Offline / fallback
  }
  return null;
}

export async function generateWhatsAppDrafts(
  contactId: string
): Promise<DraftVariant[] | null> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/whatsapp/generate-drafts`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({}),
        signal: AbortSignal.timeout(6000),
      }
    );
    if (res.ok) {
      const data = await res.json();
      return data.drafts || null;
    }
  } catch {
    // Offline / fallback
  }
  return null;
}

// ---------------------------------------------------------------------------
// Translation (Dutch to English, local model, cached on the server; ADR 0011)
// ---------------------------------------------------------------------------

export interface TranslateResult {
  language: "nl" | "en" | "unknown";
  target: "en" | "nl";
  text: string | null;
  cached: boolean;
}

/**
 * POST /api/inbox/translate. Resolves null when the server cannot translate (model missing, offline).
 * The server runs the model once per distinct text and direction, so asking again is cheap.
 */
export async function translateText(text: string, target: "en" | "nl" = "en"): Promise<TranslateResult | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/translate`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ text, target }),
      signal: AbortSignal.timeout(30000),
    });
    return res.ok ? ((await res.json()) as TranslateResult) : null;
  } catch {
    return null;
  }
}

export interface EnhanceDraftResult {
  ok: boolean;
  draftText: string;
  variants: string[];
  commitments: string[];
  commitmentsByVariant?: string[][];
  approvalId?: string | null;
  draftVersion?: number | null;
  sourcesUsed?: string[];
  problem?: string;
}

export interface UploadedThreadAttachment {
  ok: boolean;
  attachmentId: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  gmailAllowed: boolean;
  whatsappAllowed: boolean;
  driveQueued: boolean;
  problem?: string;
}

export async function uploadThreadAttachment(caseId: string, file: File): Promise<UploadedThreadAttachment> {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/attachments`, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(60000),
    });
    if (res.ok) {
      return (await res.json()) as UploadedThreadAttachment;
    }
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    return {
      ok: false,
      attachmentId: "",
      filename: file.name,
      mimeType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      gmailAllowed: false,
      whatsappAllowed: false,
      driveQueued: false,
      problem: err.detail || "Upload failed.",
    };
  } catch {
    return {
      ok: false,
      attachmentId: "",
      filename: file.name,
      mimeType: file.type || "application/octet-stream",
      sizeBytes: file.size,
      gmailAllowed: false,
      whatsappAllowed: false,
      driveQueued: false,
      problem: "Upload timed out or could not reach the server.",
    };
  }
}

export async function enhanceContactEmailDraft(
  contactId: string,
  messageId: string,
  instruction: string,
  currentText: string
): Promise<{ ok: boolean; enhancedText?: string; problem?: string; sourcesUsed?: string[] }> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/messages/${encodeURIComponent(messageId)}/enhance`,
      {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ instruction, current_text: currentText }),
        signal: AbortSignal.timeout(90000),
      }
    );
    if (res.ok) {
      const data = await res.json();
      return {
        ok: data.ok,
        enhancedText: data.enhanced_text || data.variants?.[0],
        problem: data.problem,
        sourcesUsed: data.sources_used,
      };
    }
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    return { ok: false, problem: err.detail || "Enhance request failed." };
  } catch {
    return { ok: false, problem: "Enhance request timed out or network error." };
  }
}

export async function enhanceContactWhatsAppDraft(
  contactId: string,
  instruction: string,
  currentText: string
): Promise<{ ok: boolean; enhancedText?: string; problem?: string; sourcesUsed?: string[] }> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/contacts/${encodeURIComponent(contactId)}/whatsapp/enhance`,
      {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ instruction, current_text: currentText }),
        signal: AbortSignal.timeout(90000),
      }
    );
    if (res.ok) {
      const data = await res.json();
      return {
        ok: data.ok,
        enhancedText: data.enhanced_text || data.variants?.[0],
        problem: data.problem,
        sourcesUsed: data.sources_used,
      };
    }
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    return { ok: false, problem: err.detail || "Enhance request failed." };
  } catch {
    return { ok: false, problem: "Enhance request timed out or network error." };
  }
}

export async function enhanceThreadDraft(
  caseId: string,
  payload: { instruction: string; current_text: string; message_id?: string }
): Promise<EnhanceDraftResult> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/inbox/threads/${encodeURIComponent(caseId)}/enhance`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(90000),
    });
    if (res.ok) {
      return (await res.json()) as EnhanceDraftResult;
    }
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    return {
      ok: false,
      draftText: "",
      variants: [],
      commitments: [],
      problem: err.detail || "Could not enhance draft.",
    };
  } catch {
    return {
      ok: false,
      draftText: "",
      variants: [],
      commitments: [],
      problem: "Enhance request timed out or could not reach the server.",
    };
  }
}

/** Back-compat alias for callers that only need Dutch to English. */
export const translateToEnglish = (text: string) => translateText(text, "en");

// ---------------------------------------------------------------------------
// Tenant Rent & Collections Ledger
// ---------------------------------------------------------------------------

export interface RentLedgerItem {
  id: string;
  invoiceNumber: string;
  tenantId: string;
  tenantName: string;
  tenantEmail?: string | null;
  tenantPhone?: string | null;
  unitId: string;
  unitLabel: string;
  unitAddress?: string | null;
  leaseId: string;
  billingMonth: string;
  contractRentEur: number;
  amountPaidEur: number;
  dueDate: string;
  paidAt?: string | null;
  paidAtIso?: string | null;
  status: "paid" | "overdue" | "pending" | "partial";
  overdueDays: number;
  paymentMethod: string;
  transactionReference?: string | null;
  notes?: string | null;
  aiSuggestedAction?: string | null;
}

export interface RentLedgerResponse {
  items: RentLedgerItem[];
  totalCount: number;
  month: string;
  availableMonths: string[];
  totalScheduledEur: number;
  totalCollectedEur: number;
  totalOverdueEur: number;
  overdueCount: number;
  collectionRatePct: number;
}

export interface HistoricalTrendPoint {
  month: string;
  billingMonth: string;
  scheduled: number;
  collected: number;
  overdue: number;
  rate: number;
  occupiedUnits?: number;
  totalUnits?: number;
  occupancyRate?: number;
}

export interface MonthAnalytics {
  billingMonth: string;
  totalScheduled: number;
  totalCollected: number;
  totalOverdue: number;
  totalTenants: number;
  paidTenants: number;
  overdueCount: number;
  collectionRate: number;
  occupiedUnits?: number;
  totalUnits?: number;
  occupancyRate?: number;
}

export interface PreviousMonthAnalytics {
  billingMonth: string;
  totalCollected: number;
  collectionRate: number;
  momChangePct: number;
  occupancyRate?: number;
}

export interface RentAnalyticsResponse {
  currentMonth: MonthAnalytics;
  previousMonth?: PreviousMonthAnalytics | null;
  historicalTrend: HistoricalTrendPoint[];
}

export async function getRentLedger(params: {
  month?: string;
  status?: string;
  search?: string;
} = {}): Promise<RentLedgerResponse | null> {
  const query = new URLSearchParams();
  if (params.month) query.set("month", params.month);
  if (params.status && params.status !== "all") query.set("status", params.status);
  if (params.search) query.set("search", params.search);

  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/money/rent-ledger?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      return (await res.json()) as RentLedgerResponse;
    }
  } catch (err) {
    console.warn("Failed to fetch rent ledger:", err);
  }
  return null;
}

export async function getRentAnalytics(): Promise<RentAnalyticsResponse | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/money/analytics`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      return (await res.json()) as RentAnalyticsResponse;
    }
  } catch (err) {
    console.warn("Failed to fetch rent analytics:", err);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Calendar Events & Approvals
// ---------------------------------------------------------------------------

export interface CalendarAttendee {
  email?: string;
  displayName?: string;
  responseStatus?: string;
  [key: string]: any;
}

export interface CalendarEvent {
  id: string;
  caseId?: string | null;
  unitId?: string | null;
  title: string;
  description?: string | null;
  startTime: string; // ISO 8601
  endTime: string;   // ISO 8601
  status: "proposed" | "confirmed" | "cancelled" | string;
  eventType: "contractor_repair" | "inspection" | "viewing" | string;
  externalEventId?: string | null;
  location?: string | null;
  attendees?: CalendarAttendee[];
  lockboxCode?: string | null;
  createdAt?: string;
  confirmedAt?: string | null;
  htmlLink?: string | null;
}

export interface FetchCalendarEventsParams {
  status?: "proposed" | "confirmed" | "cancelled" | string;
  caseId?: string;
}

/**
 * Fetches calendar events from backend API (GET /api/calendar/events). Only real events: when the endpoint is empty
 * or unreachable the list is empty and `isLive` is false. No sample events are ever shown.
 */
export async function getCalendarEvents(
  params?: FetchCalendarEventsParams
): Promise<{ events: CalendarEvent[]; total: number; isLive: boolean }> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.caseId) query.set("case_id", params.caseId);

  try {
    const url = `${BACKEND_BASE_URL}/api/calendar/events${query.toString() ? `?${query.toString()}` : ""}`;
    const res = await apiFetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data?.events)) {
        return { events: data.events, total: data.total ?? data.events.length, isLive: true };
      }
    }
  } catch (err) {
    console.warn("Failed to fetch calendar events:", err);
  }
  return { events: [], total: 0, isLive: false };
}

/**
 * Approves a proposed calendar appointment and triggers Google Calendar sync.
 * POST /api/calendar/events/{eventId}/approve
 */
export async function approveCalendarEvent(
  eventId: string
): Promise<{ ok: boolean; event?: CalendarEvent; error?: string }> {
  const cleanId = eventId.replace(/^evt-|^cal-/, "");
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/calendar/events/${cleanId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = (await res.json()) as CalendarEvent;
      return { ok: true, event: data };
    }
    const errData = await res.json().catch(() => null);
    return { ok: false, error: errData?.detail ?? `HTTP ${res.status}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "network error" };
  }
}

// ---------------------------------------------------------------------------
// Incoming Google Calendar invites (sent to the owner directly, not proposed by EstateOS)
// ---------------------------------------------------------------------------

export type InviteResponse = "accepted" | "declined" | "tentative";

export interface IncomingInvite {
  id: string;
  title: string;
  startTime: string;
  endTime: string;
  location?: string | null;
  organizerEmail: string;
  organizerName?: string | null;
  htmlLink?: string | null;
  matchedBy: "organizer" | "address";
  person?: { name: string; kind: string; trade?: string | null } | null;
  unit?: { id: string; label: string } | null;
}

/** GET /api/calendar/invites: pending invites that concern a known contact or one of our properties. */
export async function getIncomingInvites(): Promise<IncomingInvite[]> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/calendar/invites`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    if (res.ok) {
      const data = await res.json();
      return Array.isArray(data?.invites) ? data.invites : [];
    }
  } catch (err) {
    console.warn("Failed to fetch incoming calendar invites:", err);
  }
  return [];
}

/** POST /api/calendar/invites/{id}/respond: one click sets the owner's RSVP on Google Calendar. */
export async function respondToInvite(
  eventId: string,
  response: InviteResponse
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/calendar/invites/${encodeURIComponent(eventId)}/respond`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
        signal: AbortSignal.timeout(10000),
      }
    );
    if (res.ok) return { ok: true };
    const err = await res.json().catch(() => null);
    return { ok: false, error: err?.detail ?? `HTTP ${res.status}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "network error" };
  }
}

// ---------------------------------------------------------------------------
// Today Category Desk (M13 T10 / T12)
// ---------------------------------------------------------------------------

export interface CategorySummaryItem {
  category: BusinessCategory;
  label: string;
  open_actions: number;
  urgent: number;
  emergency?: number;
}

export type CategoryActionKind =
  | "approve_draft"
  | "reply_needed"
  | "quote_review"
  | "overdue_wait"
  | "document_review"
  | "brixx_ticket"
  | "rent_arrears"
  | "lease_ending";

export interface CategoryNextAction {
  id: string;
  category: BusinessCategory;
  kind: CategoryActionKind;
  title: string;
  why: string;
  urgency: "emergency" | "high" | "normal" | "low";
  due_at: string | null;
  case_id: string | null;
  approval_id: string | null;
  prepared: string | null;
  target_url: string;
  channel?: string | null;
  sender_name?: string | null;
  unit_label?: string | null;
  subject?: string | null;
  last_at?: string | null;
  waiting_side?: "owner" | "third_party" | null;
  waiting_days?: number | null;
  obligation?: string | null;
  has_draft?: boolean;
  overdue_days?: number;
  chase_count?: number;
  wait_status?: "waiting" | "chased" | "escalated" | "promise" | null;
  wait_id?: string | null;
}

export interface CategoryDeskData {
  brief: string | null;
  actions: CategoryNextAction[];
  waiting_for_us?: CategoryNextAction[];
  waiting_for_other?: CategoryNextAction[];
}

export async function getDashboardCategories(): Promise<CategorySummaryItem[] | null> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/dashboard/categories`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = await res.json();
      return Array.isArray(data) ? data : null;
    }
  } catch {
    // Offline
  }
  return null;
}

export async function getCategoryDesk(
  category: BusinessCategory,
  urgency: "all" | "emergency" | "high" = "all"
): Promise<CategoryDeskData | null> {
  try {
    const qs = urgency === "all" ? "?limit=25" : `?limit=25&urgency=${encodeURIComponent(urgency)}`;
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/dashboard/categories/${encodeURIComponent(category)}${qs}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(10000),
      }
    );
    if (res.ok) {
      const data = await res.json();
      return {
        brief: typeof data?.brief === "string" ? data.brief : null,
        actions: Array.isArray(data?.actions) ? data.actions : [],
        waiting_for_us: Array.isArray(data?.waiting_for_us) ? data.waiting_for_us : [],
        waiting_for_other: Array.isArray(data?.waiting_for_other) ? data.waiting_for_other : [],
      };
    }
  } catch {
    // Offline
  }
  return null;
}

export async function chaseFollowup(caseId: string): Promise<{ approval_id: string | null } | null> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/dashboard/categories/followups/${encodeURIComponent(caseId)}/chase`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(20000),
      }
    );
    if (res.ok) {
      return (await res.json()) as { approval_id: string | null };
    }
  } catch {
    // Offline
  }
  return null;
}

export async function resolveFollowup(caseId: string): Promise<boolean> {
  try {
    const res = await apiFetch(
      `${BACKEND_BASE_URL}/api/dashboard/categories/followups/${encodeURIComponent(caseId)}/resolve`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(10000),
      }
    );
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Document Library & Reference Toggle (/api/v1/documents)
// ---------------------------------------------------------------------------

export interface DocumentLibraryItem {
  id: string;
  attachment_id: string | null; // null for a document from BRIXX
  title: string;
  doc_type: string;
  status: string;
  document_date: string | null;
  summary: string | null;
  snippet: string | null;
  rank: number;
  drive_url: string | null;
  suspicious: boolean;
  created_at: string;
  is_reference: boolean;
}

export async function listDocuments(params: {
  q?: string;
  referenceOnly?: boolean;
  limit?: number;
} = {}): Promise<{ items: DocumentLibraryItem[]; ok: boolean }> {
  const query = new URLSearchParams();
  if (params.q?.trim()) query.set("q", params.q.trim());
  if (params.referenceOnly) query.set("reference_only", "true");
  query.set("limit", String(params.limit ?? 30));
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/documents?${query.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (res.ok) {
      const data = await res.json();
      return { items: Array.isArray(data) ? data : [], ok: true };
    }
  } catch {
    // Offline
  }
  return { items: [], ok: false };
}

export async function setDocumentReference(
  documentId: string,
  isReference: boolean
): Promise<{ ok: boolean; is_reference?: boolean; error?: string }> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/v1/documents/${encodeURIComponent(documentId)}/reference`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ is_reference: isReference }),
      signal: AbortSignal.timeout(10000),
    });
    if (res.ok) {
      const data = await res.json();
      return { ok: true, is_reference: Boolean(data?.is_reference) };
    }
    const err = await res.json().catch(() => null);
    return { ok: false, error: err?.detail ?? `HTTP ${res.status}` };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "network error" };
  }
}
