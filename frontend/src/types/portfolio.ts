import type { DocumentItem } from "@/components/ui/DocumentViewerModal";

/**
 * The portfolio as the pages show it. The API only stores part of it, so every field it does not know is `null`
 * (shown as "—"), never a made-up value.
 */
export type UnitStatus = "occupied" | "vacant" | "notice_given";

export interface UnitDetail {
  id: string;
  unitNumber: string; // "118-B": the label without the street
  fullAddress: string;
  complexId: string;
  complexName: string;
  status: UnitStatus;
  floor: number | null;
  areaSqm: number | null;
  monthlyRentEur: number | null;
  depositEur: number | null;
  currentTenant?: {
    name: string;
    phone: string | null;
    email: string | null;
    leaseStart: string | null;
    leaseEnd: string | null;
    rentPaidUpToDate: boolean | null;
  };
  lockboxCode: string | null;
  activeTicketCount: number | null;
  notes?: string;
}

export interface PropertyComplex {
  id: string;
  name: string; // the building: street and house number
  address: string;
  neighborhood: string | null;
  totalUnits: number;
  occupiedUnits: number; // a unit in notice still has its tenant, so it counts here
  vacantUnits: number;
  noticeGivenUnits: number;
  occupancyRate: number; // percent, from the units
  units: UnitDetail[];
}

export type RentStatus = "up_to_date" | "grace_period" | "overdue" | "unknown";

export interface TenantProfile {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  unitLabel: string;
  complexName: string | null;
  leaseStart: string | null;
  leaseEnd: string | null;
  monthlyRentEur: number | null;
  depositEur: number | null;
  rentStatus: RentStatus;
  overdueDays: number;
  overdueAmountEur?: number;
  idVerified: boolean | null;
  notes?: string;
  documents: DocumentItem[];
}
