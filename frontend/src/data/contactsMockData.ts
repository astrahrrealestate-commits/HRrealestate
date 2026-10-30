import { DocumentItem } from "@/components/ui/DocumentViewerModal";

export type ContactCategory = "contractor" | "tenant" | "owner" | "utility" | "municipal";

export interface ContactItem {
  id: string;
  name: string;
  companyName?: string;
  category: ContactCategory;
  tradeOrRole: string; // e.g. "Electrician", "Tenant", "HVAC / Verwarming", "Plumber", "Amsterdam City Inspector"
  phone: string;
  email: string;
  address?: string;
  preferredChannel: "whatsapp" | "gmail" | "phone";
  status: "active" | "inactive";
  slaAvgHours?: number; // e.g. 2.4 hrs
  openTicketsCount: number;
  rating?: number; // 4.9
  notes?: string;
  documents: DocumentItem[];
}

export const MOCK_CONTACTS: ContactItem[] = [
  {
    id: "c-1",
    name: "Kevin Chahal",
    companyName: "Chahal Bouw Electricians",
    category: "contractor",
    tradeOrRole: "Electrician / Elektricien",
    phone: "+31 6 55 55 98 12",
    email: "planning@chahalbouw.nl",
    address: "Cruquiusweg 111, 1019 AG Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    slaAvgHours: 1.8,
    openTicketsCount: 2,
    rating: 4.9,
    notes: "Preferred emergency contractor for all electrical failures. 24/7 on-call dispatch with lockbox PIN authorization.",
    documents: [
      {
        id: "doc-c1-1",
        title: "Master Service Agreement & SLA Framework 2026",
        category: "compliance",
        date: "12 Jan 2026",
        size: "1.8 MB",
        pages: 8,
        summary: "Emergency response contract: 2-hour SLA response window for power failures, fixed hourly rate €75/hr.",
      },
      {
        id: "doc-c1-2",
        title: "NEN 1010 & NEN 3140 Electrical Safety Certification",
        category: "compliance",
        date: "05 Feb 2026",
        size: "940 KB",
        pages: 4,
        summary: "Dutch standard NEN 1010 high-voltage and residential installations master certification.",
      },
      {
        id: "doc-c1-3",
        title: "Business Liability Insurance Policy (€ 2.500.000 Cover)",
        category: "compliance",
        date: "01 Jan 2026",
        size: "1.2 MB",
        pages: 6,
        summary: "Nationale-Nederlanden professional liability policy covering all residential damages.",
      },
    ],
  },
  {
    id: "c-2",
    name: "Jan Vermeer",
    companyName: "Vermeer Loodgieters",
    category: "contractor",
    tradeOrRole: "Plumber / Loodgieter",
    phone: "+31 6 22 41 89 00",
    email: "spoed@vermeerloodgieters.nl",
    address: "Westergasfabriek 18, 1014 DC Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    slaAvgHours: 2.2,
    openTicketsCount: 1,
    rating: 4.8,
    notes: "Top plumbing specialist for canal house drain blockages and pipe repairs. Handles ticket #010 leaking siphon.",
    documents: [
      {
        id: "doc-c2-1",
        title: "Plumbing Master Contractor Agreement 2026",
        category: "compliance",
        date: "15 Jan 2026",
        size: "1.5 MB",
        pages: 7,
      },
      {
        id: "doc-c2-2",
        title: "Techniek Nederland Certified Installer Accreditation",
        category: "compliance",
        date: "10 Mar 2025",
        size: "720 KB",
        pages: 3,
      },
    ],
  },
  {
    id: "c-3",
    name: "Robert van Dijk",
    companyName: "Van Dijk CV & Verwarming",
    category: "contractor",
    tradeOrRole: "Heating Engineer / CV Monteur",
    phone: "+31 6 44 22 88 19",
    email: "service@vandijkverwarming.nl",
    address: "KNSM-Laan 78, 1019 LK Amsterdam",
    preferredChannel: "gmail",
    status: "active",
    slaAvgHours: 3.5,
    openTicketsCount: 2,
    rating: 4.7,
    notes: "Authorized Vaillant and Remeha boiler service partner. Assigned to ticket #014 boiler F.22 fault and ticket #022 radiator valve.",
    documents: [
      {
        id: "doc-c3-1",
        title: "Annual Heating Maintenance Framework Agreement",
        category: "compliance",
        date: "01 Oct 2025",
        size: "2.1 MB",
        pages: 11,
      },
    ],
  },
  {
    id: "c-4",
    name: "Dennis de Bruin",
    companyName: "KeukenExpert Amsterdam",
    category: "contractor",
    tradeOrRole: "Appliance Technician",
    phone: "+31 6 98 76 54 32",
    email: "planning@keukenexpert.nl",
    address: "Spaklerweg 52, 1096 BA Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    slaAvgHours: 24,
    openTicketsCount: 1,
    rating: 4.6,
    notes: "Appliance repair and replacement quotes. Assigned to ticket #018 stove cooktop.",
    documents: [
      {
        id: "doc-c4-1",
        title: "White Goods Maintenance Price Matrix 2026",
        category: "invoice",
        date: "02 Feb 2026",
        size: "540 KB",
        pages: 2,
      },
    ],
  },
  {
    id: "c-5",
    name: "Pieter Bakker",
    category: "tenant",
    tradeOrRole: "Tenant · Pieter Floriszstraat 1 C",
    phone: "+31 6 12 34 41 87",
    email: "pieter.bakker@gmail.com",
    address: "Pieter Floriszstraat 1 C, 1018 TZ Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    openTicketsCount: 1,
    notes: "Active electrical short circuit ticket #005.",
    documents: [
      {
        id: "doc-c5-1",
        title: "ROZ Model Lease Agreement",
        category: "lease",
        date: "01 Sep 2023",
        size: "2.4 MB",
        pages: 14,
      },
    ],
  },
  {
    id: "c-6",
    name: "Gemeente Amsterdam Bouwtoezicht",
    companyName: "City of Amsterdam Housing Inspection",
    category: "municipal",
    tradeOrRole: "Municipal Inspector / Inspectie",
    phone: "+31 20 255 2222",
    email: "bouwtoezicht.centrum@amsterdam.nl",
    address: "Amstel 1 (Stopera), 1011 PN Amsterdam",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    notes: "Official municipal building safety inspector for monument permits and gas safety checks.",
    documents: [
      {
        id: "doc-c6-1",
        title: "Singel 412 Historic Canal Facade Monument Permit",
        category: "compliance",
        date: "14 May 2024",
        size: "3.5 MB",
        pages: 18,
      },
    ],
  },
];
