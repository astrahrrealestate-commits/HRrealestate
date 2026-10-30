import { DocumentItem } from "@/components/ui/DocumentViewerModal";

export interface TenantProfile {
  id: string;
  name: string;
  phone: string;
  email: string;
  unitLabel: string;
  complexName: string;
  leaseStart: string;
  leaseEnd: string;
  monthlyRentEur: number;
  depositEur: number;
  rentStatus: "up_to_date" | "grace_period" | "overdue";
  overdueDays: number;
  overdueAmountEur?: number;
  idVerified: boolean;
  notes?: string;
  documents: DocumentItem[];
}

export const MOCK_TENANTS: TenantProfile[] = [
  {
    id: "t-1",
    name: "Pieter Bakker",
    phone: "+31 6 12 34 41 87",
    email: "pieter.bakker@gmail.com",
    unitLabel: "Pieter Floriszstraat 1 C",
    complexName: "Centrum Portfolio",
    leaseStart: "01-09-2023",
    leaseEnd: "31-08-2027",
    monthlyRentEur: 1450,
    depositEur: 2900,
    rentStatus: "up_to_date",
    overdueDays: 0,
    idVerified: true,
    notes: "Active electrical ticket #005 currently in progress. Electrician Kevin dispatched.",
    documents: [
      {
        id: "doc-t1-1",
        title: "Standard Residential Tenancy Agreement (ROZ 2017)",
        category: "lease",
        date: "01 Sep 2023",
        size: "2.4 MB",
        pages: 14,
        summary: "ROZ Model tenancy agreement for Pieter Floriszstraat 1 C. Term 4 years with annual CPI inflation adjustment.",
      },
      {
        id: "doc-t1-2",
        title: "Check-in Inspection Protocol & Meter Readings",
        category: "inspection",
        date: "01 Sep 2023",
        size: "4.8 MB",
        pages: 8,
        summary: "Visual photographic handover report. Electricity meter 42918 kWh, Gas meter 1204 m3.",
      },
      {
        id: "doc-t1-3",
        title: "Verified Identity & Employment Letter (Booking.com)",
        category: "id",
        date: "18 Aug 2023",
        size: "1.1 MB",
        pages: 2,
        summary: "Dutch Passport scan and verified employer income statement showing 3.8x rent coverage.",
      },
    ],
  },
  {
    id: "t-2",
    name: "Marloes Jansen",
    phone: "+31 6 44 22 88 19",
    email: "marloes.jansen@uva.nl",
    unitLabel: "Singel 412",
    complexName: "Singel Grachtenpand",
    leaseStart: "01-11-2022",
    leaseEnd: "31-10-2026",
    monthlyRentEur: 2200,
    depositEur: 4400,
    rentStatus: "up_to_date",
    overdueDays: 0,
    idVerified: true,
    notes: "Boiler maintenance ticket #014 scheduled with Van Dijk CV.",
    documents: [
      {
        id: "doc-t2-1",
        title: "Indefinite Residential Lease Agreement",
        category: "lease",
        date: "01 Nov 2022",
        size: "2.1 MB",
        pages: 12,
        summary: "Indefinite model lease for canal apartment Singel 412. €2,200/mo bare rent.",
      },
      {
        id: "doc-t2-2",
        title: "Annual Gas & Boiler Safety Compliance Certificate",
        category: "compliance",
        date: "14 Oct 2025",
        size: "890 KB",
        pages: 3,
        summary: "Municipal CO & burner safety certification from Feenstra Amsterdam.",
      },
    ],
  },
  {
    id: "t-3",
    name: "Vipin Tyagi",
    phone: "+91 94569 16996",
    email: "vipint9902@gmail.com",
    unitLabel: "Keizersgracht 42-A",
    complexName: "Keizersgracht (42-46)",
    leaseStart: "01-01-2024",
    leaseEnd: "31-12-2027",
    monthlyRentEur: 2450,
    depositEur: 4900,
    rentStatus: "up_to_date",
    overdueDays: 11,
    overdueAmountEur: 2450,
    idVerified: true,
    notes: "October rent payment overdue past 10 days. 1 automated reminder sent via WhatsApp.",
    documents: [
      {
        id: "doc-t3-1",
        title: "Tenancy Agreement Keizersgracht 42-A",
        category: "lease",
        date: "15 Dec 2023",
        size: "3.2 MB",
        pages: 16,
        summary: "Monumental lease contract. Includes specific historic building preservation covenants.",
      },
      {
        id: "doc-t3-2",
        title: "Formal Rent Reminder Notice (1st Grace Breach)",
        category: "invoice",
        date: "11 Oct 2026",
        size: "420 KB",
        pages: 1,
        summary: "Automated payment reminder for October invoice #INV-2026-1042 (€ 2.450,-).",
      },
    ],
  },
  {
    id: "t-4",
    name: "Daan Vermeulen",
    phone: "+31 6 55 44 33 22",
    email: "daan.vermeulen@gmail.com",
    unitLabel: "Prinses Marijkestraat 2 A",
    complexName: "Marijke Complex",
    leaseStart: "01-07-2023",
    leaseEnd: "30-06-2028",
    monthlyRentEur: 1850,
    depositEur: 3700,
    rentStatus: "overdue",
    overdueDays: 9,
    overdueAmountEur: 1850,
    idVerified: true,
    notes: "Pending appliance repair for stove cooktop. Invoiced rent remains open.",
    documents: [
      {
        id: "doc-t4-1",
        title: "Tenancy Agreement Prinses Marijkestraat 2 A",
        category: "lease",
        date: "20 Jun 2023",
        size: "2.3 MB",
        pages: 13,
      },
    ],
  },
  {
    id: "t-5",
    name: "Lars van den Berg",
    phone: "+31 6 88 77 66 55",
    email: "lars@vandenberg.nl",
    unitLabel: "Henry Dunantweg 5 F",
    complexName: "Dunantweg Residences",
    leaseStart: "01-01-2023",
    leaseEnd: "31-12-2026",
    monthlyRentEur: 1390,
    depositEur: 2780,
    rentStatus: "overdue",
    overdueDays: 18,
    overdueAmountEur: 1390,
    idVerified: true,
    notes: "Notice given for move-out on 31 Dec 2026. Payment plan agreed for outstanding arrears.",
    documents: [
      {
        id: "doc-t5-1",
        title: "Lease Termination & Move-Out Confirmation Letter",
        category: "lease",
        date: "01 Oct 2026",
        size: "620 KB",
        pages: 2,
        summary: "Signed bilateral lease termination protocol effective 31 December 2026.",
      },
    ],
  },
  {
    id: "t-6",
    name: "Elena Rostova",
    phone: "+31 6 18 22 93 40",
    email: "elena.rostova@booking.com",
    unitLabel: "Keizersgracht 42-B",
    complexName: "Keizersgracht (42-46)",
    leaseStart: "15-11-2025",
    leaseEnd: "14-11-2027",
    monthlyRentEur: 2650,
    depositEur: 5300,
    rentStatus: "up_to_date",
    overdueDays: 0,
    idVerified: true,
    notes: "Expat registration complete with City of Amsterdam (Gemeente Amsterdam).",
    documents: [
      {
        id: "doc-t6-1",
        title: "Residential Lease Keizersgracht 42-B",
        category: "lease",
        date: "01 Nov 2025",
        size: "2.7 MB",
        pages: 15,
      },
    ],
  },
];
