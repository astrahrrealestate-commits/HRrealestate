import { apiFetch, BACKEND_BASE_URL } from "@/lib/backend";
import type { PropertyComplex, RentStatus, TenantProfile, UnitDetail, UnitStatus } from "@/types/portfolio";

/** What the API sends for a unit; rent 0 means "not recorded", and no lockbox code is ever returned. */
interface ApiUnit {
  id: string;
  label: string;
  address: string;
  status: string;
  monthlyRentEur: number;
  currentTenant: string | null;
  tenantPhone?: string | null;
  tenantEmail?: string | null;
  leaseStart?: string | null;
  leaseEnd: string | null;
  lockboxCode?: string | null;
  floor?: string | null;
  livingAreaSqm?: number | null;
  depositEur?: number | null;
  rentStatus?: string | null;
  activeTicketCount?: number | null;
}

interface ApiTenant {
  id: string;
  name: string;
  phone: string;
  email: string;
  unitLabel: string;
  leaseStart: string;
  leaseEnd: string;
  monthlyRentEur: number;
  rentStatus: string;
  overdueDays: number;
}

export type Loaded<T> = { ok: true; data: T } | { ok: false };

const orNull = (value: string | null | undefined) => (value ? value : null);
const knownAmount = (value: number) => (value > 0 ? value : null);
const slug = (text: string) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

/** "Prinsengracht 118-B" is unit "118-B" of the building "Prinsengracht 118". */
export function splitLabel(label: string): { building: string; unitNumber: string } {
  const match = label.trim().match(/^(.*?\s)?(\d+)(.*)$/);
  if (!match) return { building: label.trim(), unitNumber: label.trim() };
  const street = (match[1] ?? "").trim();
  const tail = match[3].replace(/^[\s-]+/, "");
  return {
    building: street ? `${street} ${match[2]}` : match[2],
    unitNumber: tail ? `${match[2]}-${tail}` : match[2],
  };
}

const asStatus = (value: string): UnitStatus =>
  value === "occupied" || value === "notice_given" ? value : "vacant";

function toUnit(unit: ApiUnit): UnitDetail {
  const { building, unitNumber } = splitLabel(unit.label);
  const status = asStatus(unit.status);
  const rent = knownAmount(unit.monthlyRentEur);
  return {
    id: unit.id,
    unitNumber,
    fullAddress: unit.address,
    complexId: slug(building),
    complexName: building,
    status,
    floor: unit.floor ? Number.parseInt(unit.floor, 10) || null : null,
    areaSqm: unit.livingAreaSqm ?? null,
    monthlyRentEur: rent,
    depositEur: unit.depositEur ? unit.depositEur : null,
    currentTenant: unit.currentTenant
      ? {
          name: unit.currentTenant,
          phone: orNull(unit.tenantPhone),
          email: orNull(unit.tenantEmail),
          leaseStart: orNull(unit.leaseStart),
          leaseEnd: orNull(unit.leaseEnd),
          rentPaidUpToDate: unit.rentStatus === "overdue" ? false : unit.rentStatus === "up_to_date" ? true : null,
        }
      : undefined,
    lockboxCode: orNull(unit.lockboxCode),
    activeTicketCount: unit.activeTicketCount ?? 0,
  };
}

/** Group units into buildings and take every count from the units themselves, so counts and cards cannot disagree. */
export function buildComplexes(apiUnits: ApiUnit[]): PropertyComplex[] {
  const byBuilding = new Map<string, UnitDetail[]>();
  for (const unit of apiUnits.map(toUnit)) {
    byBuilding.set(unit.complexId, [...(byBuilding.get(unit.complexId) ?? []), unit]);
  }
  return [...byBuilding.entries()]
    .map(([id, units]) => {
      const sorted = [...units].sort((a, b) => a.unitNumber.localeCompare(b.unitNumber, undefined, { numeric: true }));
      const vacant = sorted.filter((u) => u.status === "vacant").length;
      const notice = sorted.filter((u) => u.status === "notice_given").length;
      return {
        id,
        name: sorted[0].complexName,
        address: sorted[0].fullAddress,
        neighborhood: null,
        totalUnits: sorted.length,
        occupiedUnits: sorted.length - vacant,
        vacantUnits: vacant,
        noticeGivenUnits: notice,
        occupancyRate: Math.round(((sorted.length - vacant) / sorted.length) * 1000) / 10,
        units: sorted,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
}

export async function getPortfolio(): Promise<Loaded<PropertyComplex[]>> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/properties`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return { ok: false };
    const body: { units?: ApiUnit[] } = await res.json();
    return { ok: true, data: buildComplexes(body.units ?? []) };
  } catch {
    return { ok: false };
  }
}

const asRentStatus = (value: string): RentStatus =>
  value === "up_to_date" || value === "grace_period" || value === "overdue" ? value : "unknown";

export async function getTenantProfiles(): Promise<Loaded<TenantProfile[]>> {
  try {
    const res = await apiFetch(`${BACKEND_BASE_URL}/api/tenants`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) return { ok: false };
    const body: { tenants?: ApiTenant[] } = await res.json();
    const data = (body.tenants ?? []).map((t) => {
      const rent = knownAmount(t.monthlyRentEur);
      return {
        id: t.id,
        name: t.name,
        phone: orNull(t.phone),
        email: orNull(t.email),
        unitLabel: t.unitLabel,
        complexName: t.unitLabel ? splitLabel(t.unitLabel).building : null,
        leaseStart: orNull(t.leaseStart),
        leaseEnd: orNull(t.leaseEnd),
        monthlyRentEur: rent,
        depositEur: null,
        rentStatus: asRentStatus(t.rentStatus),
        overdueDays: t.overdueDays,
        idVerified: null,
        documents: [] as TenantProfile["documents"],
      };
    });
    return { ok: true, data };
  } catch {
    return { ok: false };
  }
}
