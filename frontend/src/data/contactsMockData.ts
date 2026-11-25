import { DocumentItem } from "@/components/ui/DocumentViewerModal";

export type ContactCategory =
  | "contractor"
  | "tenant"
  | "owner"
  | "legal"
  | "vve"
  | "business"
  | "utility"
  | "municipal"
  | "other";

export type AgentUnderstandingCategory =
  | "maintenance"
  | "payment"
  | "lease"
  | "complaint"
  | "contractor_update"
  | "admin"
  | "spam"
  | "other";

export interface AIDraftVariant {
  id: "d1" | "d2" | "d3" | string;
  label: string;
  body: string;
}

export interface ContactEmailItem {
  id: string;
  sender: string;
  senderEmail: string;
  subject: string;
  snippet: string;
  body: string;
  date: string;
  time: string;
  isUnread?: boolean;
  hasAttachments?: boolean;
  isHistorical?: boolean;
  category?: AgentUnderstandingCategory | string;
  priority?: "emergency" | "high" | "normal" | "low";
  starred?: boolean;
  draftVariants?: AIDraftVariant[];
}

export interface ContactWhatsAppMessage {
  id: string;
  sender: "tenant" | "owner";
  text: string;
  time: string;
  date: string;
  status?: "sent" | "delivered" | "read";
}

export interface ContactLeaseAgreement {
  id: string;
  title: string;
  period: string;
  monthlyRent: string;
  deposit: string;
  signedDate: string;
  status: "active" | "pending_renewal" | "expired";
  documentUrl?: string;
  fileSize: string;
}

export interface ContactItem {
  id: string;
  name: string;
  avatarUrl?: string;
  category: ContactCategory;
  tradeOrRole?: string;
  unitRole?: string;
  phone: string;
  email: string;
  secondaryPhones?: string[];
  secondaryEmails?: string[];
  address?: string;
  propertyAddress: string;
  residentialAddress: string;
  agreementPeriod: string;
  preferredChannel?: "gmail" | "whatsapp";
  status: "active" | "inactive" | "pending" | "ended" | "ending_soon" | string;
  unclassified?: boolean;
  rentStatus?: "up_to_date" | "overdue" | "unknown" | string;
  monthlyRentEur?: number | null; // from the lease's BRIXX contract; null when unknown
  depositEur?: number | null;
  leaseStart?: string | null; // dd-mm-yyyy
  leaseEnd?: string | null; // null for an open-ended lease
  openTicketsCount: number;
  rating?: number;
  notes?: string;
  documents: DocumentItem[];
  emails: ContactEmailItem[];
  whatsappMessages: ContactWhatsAppMessage[];
  suggestedWhatsAppDrafts?: AIDraftVariant[];
  leases: ContactLeaseAgreement[];
}

export const MOCK_CONTACTS: ContactItem[] = [
  {
    id: "t-1",
    name: "Sanne de Vries",
    category: "tenant",
    tradeOrRole: "Tenant · Keizersgracht 42-A",
    unitRole: "Keizersgracht 42-A",
    phone: "+31 6 5550 0101",
    email: "sanne.devries@example.test",
    propertyAddress: "Keizersgracht 42-A, 1015 CS Amsterdam",
    residentialAddress: "Keizersgracht 42-A, 1015 CS Amsterdam",
    agreementPeriod: "01 Jan 2024 — 31 Dec 2024",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 5.0,
    notes: "Main leaseholder for Keizersgracht 42-A. Punctual rent payment via SEPA direct debit.",
    documents: [
      {
        id: "doc-sdv-1",
        title: "ROZ Model Residential Lease Agreement 2024",
        category: "lease",
        date: "01 Jan 2024",
        size: "2.4 MB",
        pages: 14,
        summary: "Standard 12-month ROZ Dutch residential lease for Keizersgracht 42-A. Monthly rent € 2.450.",
      },
    ],
    leases: [
      {
        id: "l-sdv-1",
        title: "ROZ Model Residential Lease Agreement",
        period: "01 Jan 2024 — 31 Dec 2024",
        monthlyRent: "€ 2.450,00",
        deposit: "€ 4.900,00",
        signedDate: "18 Dec 2023",
        status: "active",
        fileSize: "2.4 MB",
      },
    ],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "t-2",
    name: "Marcus Vance",
    category: "tenant",
    tradeOrRole: "Tenant · Unit 12",
    unitRole: "Unit 12 · 14-22 St. Mark's Square",
    phone: "+44 7700 900012",
    email: "marcus.vance@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 12, London EC1A 1BB",
    agreementPeriod: "01 Jan 2024 – 31 Dec 2024",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 1,
    rating: 4.8,
    notes: "Key tenant. Active lease agreement in review.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "t-3",
    name: "Elena Rostova",
    category: "tenant",
    tradeOrRole: "Tenant · Unit 8",
    unitRole: "Unit 8 · 14-22 St. Mark's Square",
    phone: "+44 7700 900034",
    email: "elena.rostova@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 8, London EC1A 1BB",
    agreementPeriod: "15 Mar 2024 – 14 Mar 2025",
    preferredChannel: "whatsapp",
    status: "active",
    openTicketsCount: 0,
    rating: 5.0,
    notes: "Prompt payment record.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "t-4",
    name: "Sarah Jenkins",
    category: "tenant",
    tradeOrRole: "Tenant · Unit 4",
    unitRole: "Unit 4 · 14-22 St. Mark's Square",
    phone: "+44 7700 900056",
    email: "sarah.j@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 4, London EC1A 1BB",
    agreementPeriod: "01 Jun 2024 – 31 May 2025",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 4.9,
    notes: "Active leaseholder.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "t-5",
    name: "David Kim",
    category: "tenant",
    tradeOrRole: "Tenant · Unit 15",
    unitRole: "Unit 15 · 14-22 St. Mark's Square",
    phone: "+44 7700 900078",
    email: "david.kim@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 15, London EC1A 1BB",
    agreementPeriod: "01 Sep 2023 – 31 Aug 2024",
    preferredChannel: "whatsapp",
    status: "active",
    openTicketsCount: 0,
    rating: 4.7,
    notes: "Lease up for renewal.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "t-6",
    name: "Priya Patel",
    category: "tenant",
    tradeOrRole: "Tenant · Unit 3",
    unitRole: "Unit 3 · 14-22 St. Mark's Square",
    phone: "+44 7700 900090",
    email: "priya.p@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 3, London EC1A 1BB",
    agreementPeriod: "01 Feb 2024 – 31 Jan 2025",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 5.0,
    notes: "Verified tenant.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "c-1",
    name: "CityFlow Plumbing",
    category: "contractor",
    tradeOrRole: "Plumbing & Heating Services",
    unitRole: "Emergency Contractor",
    phone: "+44 7700 900111",
    email: "dispatch@cityflow.co.uk",
    propertyAddress: "Service Radius: Greater London",
    residentialAddress: "Depot 4, Industrial Way, London SE1 0AA",
    agreementPeriod: "Master Service Agreement Active",
    preferredChannel: "whatsapp",
    status: "active",
    openTicketsCount: 2,
    rating: 4.9,
    notes: "Primary approved plumbing contractor. SLA 2h response.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
  {
    id: "c-2",
    name: "Apex Heating Solutions",
    category: "contractor",
    tradeOrRole: "HVAC & Boiler Specialists",
    unitRole: "HVAC Contractor",
    phone: "+44 7700 900222",
    email: "repairs@apexheating.co.uk",
    propertyAddress: "Service Radius: Greater London",
    residentialAddress: "Unit 7, Apex Park, London N1 7XX",
    agreementPeriod: "Master Service Agreement Active",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 4.8,
    notes: "Boiler certifications and annual service inspections.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
    suggestedWhatsAppDrafts: [],
  },
];
