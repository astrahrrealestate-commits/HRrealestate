import { apiFetch, BACKEND_BASE_URL } from "@/lib/backend";
import { formatDate, formatStamp } from "@/lib/clock";
import type { ReportKind, ReportRow, ReportTemplate } from "@/types/reports";

/** Roles that see money and activity reports; any other signed-in role sees the unit and ticket reports only. */
const ALL_ROLES = ["owner", "manager", "admin", "viewer"] as const;
const MONEY_ROLES = ["owner", "manager", "admin"] as const;

export const REPORT_IDS: readonly ReportKind[] = ["occupancy", "arrears", "maintenance", "log"];

export function isReportId(value: string | null): value is ReportKind {
  return REPORT_IDS.includes(value as ReportKind);
}

type Fetched<T> = { ok: true; data: T } | { ok: false; status: number };

async function getJson<T>(path: string): Promise<Fetched<T>> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}${path}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return { ok: false, status: res.status };
    return { ok: true, data: (await res.json()) as T };
  } catch {
    return { ok: false, status: 0 };
  }
}

const dash = (value: string | null | undefined) => (value && value.trim() ? value : "—");
const euro = (amount: number) => (amount > 0 ? `€ ${amount.toLocaleString("nl-NL")},-` : "—");

/** The API writes lease dates as dd-mm-yyyy. */
function parseLeaseEnd(value: string | null | undefined): Date | null {
  const m = value?.match(/^(\d{2})-(\d{2})-(\d{4})$/);
  return m ? new Date(Date.UTC(Number(m[3]), Number(m[2]) - 1, Number(m[1]), 23, 59, 59)) : null;
}

interface ApiUnit {
  label: string;
  status: string;
  monthlyRentEur: number;
  currentTenant: string | null;
  leaseEnd: string | null;
  livingAreaSqm?: number | null;
  address: string;
}

interface ApiTenant {
  name: string;
  unitLabel: string;
  rentStatus: string;
  overdueDays: number;
  monthlyRentEur: number;
}

interface ApiTicket {
  ticketNumber: string;
  unitLabel: string;
  issueTitle: string;
  contractorName: string;
  poBudgetCap: string;
  status: string;
  isOverdue?: boolean;
}

interface ApiLog {
  id: string;
  timestamp: string;
  actionText: string;
  entityRef: string;
  tag: string;
}

const STATUS_LABEL: Record<string, string> = {
  occupied: "Occupied",
  vacant: "Vacant",
  notice_given: "Notice given",
};

/** Unit status as the lease dates say it: an occupied unit whose lease ended before today is not "Occupied". */
export function unitStatus(status: string, leaseEnd: string | null, now: Date): string {
  const end = parseLeaseEnd(leaseEnd);
  if (status === "occupied" && end && end < now) return "Lease ended";
  return STATUS_LABEL[status] ?? "Unknown";
}

function splitBuilding(label: string): string {
  const m = label.trim().match(/^(.*?\s)?(\d+)/);
  return m ? `${(m[1] ?? "").trim()} ${m[2]}`.trim() : label.trim();
}

/** Non-overlapping arrears buckets: 1-30, 31-90, 91+ days overdue. */
export function arrearsBucket(days: number): string {
  if (days <= 30) return "1–30 days";
  if (days <= 90) return "31–90 days";
  return "91+ days";
}

const empty = (
  id: ReportKind,
  name: string,
  description: string,
  period: string,
  columns: string[],
  roles: readonly string[],
  emptyMessage: string,
): ReportTemplate => ({ id, name, description, period, columns, rows: [], emptyMessage, failed: false, roles });

function occupancy(units: Fetched<{ units?: ApiUnit[] }>, now: Date): ReportTemplate {
  const base = empty(
    "occupancy",
    "Portfolio Occupancy & Lease Roll",
    "Unit-by-unit tenancy status, monthly contract rent and lease end dates, read live from your portfolio. A dash means it is not recorded; open-ended means the lease has no end date.",
    `As of ${formatDate(now)}`,
    ["Unit", "Complex", "Tenant", "Status", "Sqm", "Rent / Mo", "Lease End"],
    ALL_ROLES,
    "No units are recorded yet.",
  );
  if (!units.ok) return { ...base, failed: true };
  const rows: ReportRow[] = (units.data.units ?? []).map((u) => ({
    Unit: u.label,
    Complex: splitBuilding(u.label),
    Tenant: u.currentTenant ?? "Vacant",
    Status: unitStatus(u.status, u.leaseEnd, now),
    Sqm: u.livingAreaSqm ? String(u.livingAreaSqm) : "—",
    "Rent / Mo": euro(u.monthlyRentEur),
    "Lease End": u.leaseEnd ? u.leaseEnd : u.currentTenant ? "Open-ended" : "—",
  }));
  return { ...base, rows };
}

function arrears(tenants: Fetched<{ tenants?: ApiTenant[] }>, now: Date): ReportTemplate {
  const base = empty(
    "arrears",
    "Rent Arrears & Aging Ledger",
    "Tenants with overdue rent, in non-overlapping buckets: 1–30, 31–90 and 91+ days. Tenants whose rent is not tracked yet are not listed.",
    `As of ${formatDate(now)}`,
    ["Unit", "Tenant", "Amount Due", "Overdue Days", "Bucket"],
    MONEY_ROLES,
    "No overdue rent. Rent payments are not mirrored yet, so this stays empty until they are.",
  );
  if (!tenants.ok) return { ...base, failed: true };
  const rows: ReportRow[] = (tenants.data.tenants ?? [])
    .filter((t) => t.rentStatus === "overdue" && t.overdueDays > 0)
    .sort((a, b) => b.overdueDays - a.overdueDays)
    .map((t) => ({
      Unit: dash(t.unitLabel),
      Tenant: t.name,
      "Amount Due": euro(t.monthlyRentEur),
      "Overdue Days": `${t.overdueDays} days`,
      Bucket: arrearsBucket(t.overdueDays),
    }));
  return { ...base, rows };
}

const TICKET_STATUS: Record<string, string> = {
  pending_approval: "Pending approval",
  dispatched: "Dispatched",
  scheduled: "Scheduled",
  completed: "Completed",
};

function maintenance(tickets: Fetched<{ tickets?: ApiTicket[] }>, now: Date): ReportTemplate {
  const base = empty(
    "maintenance",
    "Maintenance Dispatch & PO Summary",
    "Every maintenance ticket with its contractor, budget cap and status, the same figures the Maintenance page shows. There is no SLA column until tickets carry real SLA timestamps.",
    `As of ${formatDate(now)}`,
    ["Ticket", "Unit", "Issue", "Contractor", "Budget Cap", "Status"],
    ALL_ROLES,
    "No maintenance tickets.",
  );
  if (!tickets.ok) return { ...base, failed: true };
  const rows: ReportRow[] = (tickets.data.tickets ?? []).map((t) => ({
    Ticket: t.ticketNumber,
    Unit: t.unitLabel,
    Issue: t.issueTitle,
    Contractor: t.contractorName,
    "Budget Cap": dash(t.poBudgetCap),
    Status: t.isOverdue ? "Overdue" : (TICKET_STATUS[t.status] ?? t.status),
  }));
  return { ...base, rows };
}

/** "2026-11-10 08:15 UTC" from the API, shown in the company's zone with the real date. */
function logStamp(raw: string): string {
  const parsed = new Date(raw.replace(" UTC", "Z").replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? dash(raw) : formatStamp(parsed);
}

function autonomousLog(logs: Fetched<{ logs?: ApiLog[] }>): ReportTemplate {
  const base = empty(
    "log",
    "EstateOS Autonomous Log",
    "The latest actions EstateOS completed for you, such as replies sent after you approved them.",
    "Latest 20 actions",
    ["Timestamp", "Entity", "Autonomous Operation", "Trigger"],
    MONEY_ROLES,
    "Nothing has been sent yet.",
  );
  if (!logs.ok) return { ...base, failed: true };
  const rows: ReportRow[] = (logs.data.logs ?? []).map((l) => ({
    Timestamp: logStamp(l.timestamp),
    Entity: l.entityRef,
    "Autonomous Operation": l.actionText,
    Trigger: l.tag === "send" ? "Owner approved" : l.tag,
  }));
  return { ...base, rows };
}

export type ReportsLoad = { reports: ReportTemplate[]; sessionExpired: boolean; loadedAt: Date };

/** Reads the four sources in parallel. A source that fails marks only its own report as failed. */
export async function loadReports(): Promise<ReportsLoad> {
  const now = new Date();
  const [units, tenants, tickets, logs] = await Promise.all([
    getJson<{ units?: ApiUnit[] }>("/api/properties"),
    getJson<{ tenants?: ApiTenant[] }>("/api/tenants"),
    getJson<{ tickets?: ApiTicket[] }>("/api/maintenance/tickets"),
    getJson<{ logs?: ApiLog[] }>("/api/dashboard/logs?limit=20"),
  ]);
  const sessionExpired = [units, tenants, tickets, logs].some((r) => !r.ok && (r.status === 401 || r.status === 403));
  return {
    reports: [occupancy(units, now), arrears(tenants, now), maintenance(tickets, now), autonomousLog(logs)],
    sessionExpired,
    loadedAt: now,
  };
}
