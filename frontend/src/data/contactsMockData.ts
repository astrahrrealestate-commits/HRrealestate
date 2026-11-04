import { DocumentItem } from "@/components/ui/DocumentViewerModal";

export type ContactCategory = "contractor" | "tenant" | "owner" | "utility" | "municipal";

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
  category?: "lease" | "rent" | "maintenance" | "general";
  starred?: boolean;
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
  companyName?: string;
  category: ContactCategory;
  tradeOrRole: string; // e.g. "Tenant", "Electrician", "Plumber"
  phone: string;
  email: string;
  address?: string;
  propertyAddress?: string;
  residentialAddress?: string;
  unitRole?: string;
  agreementPeriod?: string;
  preferredChannel: "whatsapp" | "gmail" | "phone";
  status: "active" | "inactive";
  slaAvgHours?: number;
  openTicketsCount: number;
  rating?: number;
  notes?: string;
  documents: DocumentItem[];
  emails: ContactEmailItem[];
  whatsappMessages: ContactWhatsAppMessage[];
  leases: ContactLeaseAgreement[];
}

export const MOCK_CONTACTS: ContactItem[] = [
  {
    id: "t-1",
    name: "Marcus Vance",
    avatarUrl: "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=200&auto=format&fit=crop&q=80",
    category: "tenant",
    tradeOrRole: "Tenant",
    unitRole: "Unit 12",
    phone: "+44 7700 900012",
    email: "marcus.vance@email.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 12, London EC1A 1BB",
    agreementPeriod: "01 Jan 2024 — 31 Dec 2024",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 5.0,
    notes: "Prompt rent payer. Requested lease renewal draft for 2025.",
    documents: [
      {
        id: "doc-mv-1",
        title: "Assured Shorthold Tenancy Agreement 2024",
        category: "lease",
        date: "01 Jan 2024",
        size: "2.4 MB",
        pages: 14,
        summary: "Standard 12-month residential AST for Unit 12. Monthly rent £2,450.",
      },
      {
        id: "doc-mv-2",
        title: "Deposit Protection Service Certificate (£ 2.825)",
        category: "compliance",
        date: "05 Jan 2024",
        size: "680 KB",
        pages: 2,
        summary: "DPS government insured custodial scheme deposit reference #DPS-889124.",
      },
      {
        id: "doc-mv-3",
        title: "Inventory & Check-in Condition Report",
        category: "compliance",
        date: "02 Jan 2024",
        size: "5.1 MB",
        pages: 28,
        summary: "Full photographic inventory of Unit 12 with meter readings.",
      },
    ],
    leases: [
      {
        id: "l-mv-1",
        title: "Residential Tenancy Agreement (AST)",
        period: "01 Jan 2024 — 31 Dec 2024",
        monthlyRent: "£2,450.00",
        deposit: "£2,825.00",
        signedDate: "18 Dec 2023",
        status: "active",
        fileSize: "2.4 MB",
      },
      {
        id: "l-mv-2",
        title: "Upcoming Lease Extension Addendum 2025",
        period: "01 Jan 2025 — 31 Dec 2025",
        monthlyRent: "£2,550.00",
        deposit: "£2,825.00 (Held)",
        signedDate: "Pending Review",
        status: "pending_renewal",
        fileSize: "1.1 MB",
      },
    ],
    emails: [
      {
        id: "m-1",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "Lease renewal documents attached for review and signature",
        snippet: "Hi Harjot, I have reviewed the proposed 2025 lease terms and attached the countersigned addendum for Unit 12.",
        body: "Hi Harjot,\n\nI have reviewed the proposed 2025 lease terms and attached the countersigned addendum for Unit 12. Everything looks clear regarding the indexation adjustment. Could you please send back the fully executed copy once countersigned on your end?\n\nBest regards,\nMarcus Vance",
        date: "Today",
        time: "13:26",
        isUnread: true,
        hasAttachments: true,
        category: "lease",
      },
      {
        id: "m-2",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "Confirming receipt of this month's rent payment. Thank you!",
        snippet: "Good morning, just a quick note to confirm that November rent was transferred via standing order earlier today.",
        body: "Good morning,\n\nJust a quick note to confirm that November rent was transferred via standing order earlier today. Please let me know once your ledger reflects the incoming transfer.\n\nThanks,\nMarcus",
        date: "Today",
        time: "10:14",
        isUnread: false,
        hasAttachments: false,
        category: "rent",
      },
      {
        id: "m-3",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "Parking space allocation query regarding visitor passes",
        snippet: "Hello, could you let me know the procedure to obtain a guest parking permit for next weekend? My brother is visiting.",
        body: "Hello,\n\nCould you let me know the procedure to obtain a guest parking permit for next weekend? My brother is visiting from Bristol from Friday to Sunday.\n\nThank you,\nMarcus Vance",
        date: "Yesterday",
        time: "Yesterday",
        isUnread: false,
        hasAttachments: false,
        category: "general",
      },
      {
        id: "m-4",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "Scheduled inspection update for next Wednesday morning",
        snippet: "Thanks for the advance notice about the routine building electrical inspection. The 10:00 AM slot works fine for me.",
        body: "Hi Harjot,\n\nThanks for the advance notice regarding the routine building electrical inspection. The 10:00 AM slot on Wednesday works fine for me, I will be working from home.\n\nBest,\nMarcus",
        date: "Yesterday",
        time: "Yesterday",
        isUnread: false,
        hasAttachments: false,
        category: "maintenance",
      },
      {
        id: "m-5",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "AC unit filter replacement instructions requested",
        snippet: "Hi, I noticed the AC filter warning light flashed on the hallway thermostat. Do you supply replacement filters or should I order them?",
        body: "Hi,\n\nI noticed the filter warning light flashed on the hallway thermostat unit yesterday. Do you supply standard HEPA replacement filters or should I order the approved model directly?\n\nRegards,\nMarcus",
        date: "01 Nov 2026",
        time: "1 Nov",
        isUnread: false,
        hasAttachments: false,
        category: "maintenance",
      },
      {
        id: "m-6",
        sender: "Marcus Vance",
        senderEmail: "marcus.vance@email.com",
        subject: "Welcome to EstateOS! Getting started guide and portal credentials",
        snippet: "Historical onboarding message: Tenancy onboarding confirmed. Keys collected on 1 Jan 2024 from management desk.",
        body: "Dear Marcus,\n\nWelcome to your tenancy at Unit 12. Your keys have been verified and access codes for the front lobby intercom are activated.\n\nPlease keep this email for your historical reference.\n\nEstateOS Management",
        date: "15 Oct 2024",
        time: "15 Oct",
        isUnread: false,
        hasAttachments: true,
        isHistorical: true,
        category: "general",
      },
    ],
    whatsappMessages: [
      {
        id: "wa-1",
        sender: "tenant",
        text: "Hi Harjot, parcel delivery arrived for Unit 12 downstairs. All set, thank you!",
        date: "Today",
        time: "11:05",
        status: "read",
      },
      {
        id: "wa-2",
        sender: "owner",
        text: "Great to hear Marcus! Let me know if you need any assistance with anything else.",
        date: "Today",
        time: "11:12",
        status: "read",
      },
      {
        id: "wa-3",
        sender: "tenant",
        text: "Will do! Have sent the signed lease draft over email just now.",
        date: "Today",
        time: "13:28",
        status: "read",
      },
    ],
  },
  {
    id: "t-2",
    name: "Elena Rostova",
    avatarUrl: "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=200&auto=format&fit=crop&q=80",
    category: "tenant",
    tradeOrRole: "Tenant",
    unitRole: "Unit 4 B",
    phone: "+31 6 82 91 04 22",
    email: "elena.rostova@gmail.com",
    propertyAddress: "Keizersgracht 482, 1016 EG Amsterdam",
    residentialAddress: "Keizersgracht 482, Apt 4 B, 1016 EG Amsterdam",
    agreementPeriod: "01 Mar 2024 — 28 Feb 2025",
    preferredChannel: "whatsapp",
    status: "active",
    openTicketsCount: 0,
    rating: 4.9,
    notes: "High reliability tenant. Clean inspection records.",
    documents: [
      {
        id: "doc-er-1",
        title: "ROZ Model Lease Agreement 2024",
        category: "lease",
        date: "01 Mar 2024",
        size: "2.1 MB",
        pages: 12,
      },
    ],
    leases: [
      {
        id: "l-er-1",
        title: "ROZ Model Residential Lease",
        period: "01 Mar 2024 — 28 Feb 2025",
        monthlyRent: "€ 1.950,00",
        deposit: "€ 3.900,00",
        signedDate: "15 Feb 2024",
        status: "active",
        fileSize: "2.1 MB",
      },
    ],
    emails: [
      {
        id: "m-er-1",
        sender: "Elena Rostova",
        senderEmail: "elena.rostova@gmail.com",
        subject: "Monthly rent confirmation and utility statement request",
        snippet: "Hi Harjot, transfer for this month has been sent. Could you share the annual service charges overview?",
        body: "Hi Harjot,\n\nTransfer for this month has been sent. Could you please share the annual service charges breakdown when available?\n\nBest,\nElena",
        date: "02 Nov 2026",
        time: "02 Nov",
        isUnread: false,
        category: "rent",
      },
      {
        id: "m-er-2",
        sender: "Elena Rostova",
        senderEmail: "elena.rostova@gmail.com",
        subject: "Historical Onboarding & Key Handover Protocol",
        snippet: "Handover protocol signed on entry with photographic meters check.",
        body: "Attached is the signed handover protocol from March entry.\n\nElena Rostova",
        date: "01 Mar 2024",
        time: "Mar 2024",
        isUnread: false,
        isHistorical: true,
        hasAttachments: true,
        category: "general",
      },
    ],
    whatsappMessages: [
      {
        id: "wa-er-1",
        sender: "tenant",
        text: "Hi Harjot, hope you have a nice week! Rent transferred today.",
        date: "02 Nov",
        time: "09:40",
        status: "read",
      },
    ],
  },
  {
    id: "t-3",
    name: "Sarah Jenkins",
    avatarUrl: "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=200&auto=format&fit=crop&q=80",
    category: "tenant",
    tradeOrRole: "Tenant",
    unitRole: "Unit 8",
    phone: "+44 7700 900341",
    email: "sarah.jenkins@outlook.com",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 8, London EC1A 1BB",
    agreementPeriod: "01 Jun 2024 — 31 May 2025",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 4.8,
    notes: "Quiet tenant, prompt communications.",
    documents: [],
    leases: [
      {
        id: "l-sj-1",
        title: "Standard Residential Tenancy AST",
        period: "01 Jun 2024 — 31 May 2025",
        monthlyRent: "£2,100.00",
        deposit: "£2,423.00",
        signedDate: "20 May 2024",
        status: "active",
        fileSize: "1.9 MB",
      },
    ],
    emails: [
      {
        id: "m-sj-1",
        sender: "Sarah Jenkins",
        senderEmail: "sarah.jenkins@outlook.com",
        subject: "Window seal inspection follow up",
        snippet: "Thanks for having the glazier inspect the window seal last week, the draught is completely resolved.",
        body: "Hi Harjot,\n\nThanks for having the glazier inspect the window seal last week. The draught is completely resolved now.\n\nBest wishes,\nSarah",
        date: "28 Oct 2026",
        time: "28 Oct",
        isUnread: false,
        category: "maintenance",
      },
    ],
    whatsappMessages: [],
  },
  {
    id: "t-4",
    name: "David Kim",
    avatarUrl: "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200&auto=format&fit=crop&q=80",
    category: "tenant",
    tradeOrRole: "Tenant",
    unitRole: "Unit 3 A",
    phone: "+31 6 99 12 34 56",
    email: "david.kim@techcorp.io",
    propertyAddress: "Keizersgracht 482, 1016 EG Amsterdam",
    residentialAddress: "Keizersgracht 482, Unit 3 A, 1016 EG Amsterdam",
    agreementPeriod: "01 Sep 2024 — 31 Aug 2025",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 5.0,
    documents: [],
    leases: [
      {
        id: "l-dk-1",
        title: "Fixed-Term Expat Tenancy Lease",
        period: "01 Sep 2024 — 31 Aug 2025",
        monthlyRent: "€ 2.200,00",
        deposit: "€ 4.400,00",
        signedDate: "15 Aug 2024",
        status: "active",
        fileSize: "2.3 MB",
      },
    ],
    emails: [
      {
        id: "m-dk-1",
        sender: "David Kim",
        senderEmail: "david.kim@techcorp.io",
        subject: "High-speed fiber internet hookup confirmation",
        snippet: "KPN technician visited and activated the Gigabit fiber connection in unit 3 A. All tests are optimal.",
        body: "Hi Harjot,\n\nJust confirming the fiber technician concluded the router setup. Speeds are working great.\n\nBest,\nDavid",
        date: "14 Oct 2026",
        time: "14 Oct",
        isUnread: false,
        category: "general",
      },
    ],
    whatsappMessages: [],
  },
  {
    id: "t-5",
    name: "Priya Patel",
    avatarUrl: "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=200&auto=format&fit=crop&q=80",
    category: "tenant",
    tradeOrRole: "Tenant",
    unitRole: "Unit 15",
    phone: "+44 7700 900554",
    email: "priya.patel@designstudio.uk",
    propertyAddress: "14-22 St. Mark's Square, London EC1A 1BB",
    residentialAddress: "14-22 St. Mark's Square, Unit 15, London EC1A 1BB",
    agreementPeriod: "15 Jul 2024 — 14 Jul 2025",
    preferredChannel: "gmail",
    status: "active",
    openTicketsCount: 0,
    rating: 4.9,
    documents: [],
    leases: [
      {
        id: "l-pp-1",
        title: "Standard Residential Tenancy AST",
        period: "15 Jul 2024 — 14 Jul 2025",
        monthlyRent: "£2,350.00",
        deposit: "£2,711.00",
        signedDate: "01 Jul 2024",
        status: "active",
        fileSize: "2.0 MB",
      },
    ],
    emails: [
      {
        id: "m-pp-1",
        sender: "Priya Patel",
        senderEmail: "priya.patel@designstudio.uk",
        subject: "Bicycle storage rack allocation in basement",
        snippet: "Hi Harjot, requested permit for rack slot #15 in the secure bike shelter.",
        body: "Hi Harjot,\n\nCould you confirm if slot #15 in the basement bike store is registered to Unit 15?\n\nMany thanks,\nPriya",
        date: "20 Oct 2026",
        time: "20 Oct",
        isUnread: false,
        category: "general",
      },
    ],
    whatsappMessages: [],
  },
  {
    id: "c-1",
    name: "Kevin Chahal",
    avatarUrl: "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200&auto=format&fit=crop&q=80",
    companyName: "Chahal Bouw Electricians",
    category: "contractor",
    tradeOrRole: "Electrician / Elektricien",
    phone: "+31 6 55 55 98 12",
    email: "planning@chahalbouw.nl",
    address: "Cruquiusweg 111, 1019 AG Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    slaAvgHours: 1.8,
    openTicketsCount: 0,
    rating: 4.9,
    notes: "Preferred emergency contractor for all electrical failures. 24/7 on-call dispatch with lockbox PIN authorization.",
    documents: [],
    leases: [],
    emails: [
      {
        id: "m-kc-1",
        sender: "Kevin Chahal",
        senderEmail: "planning@chahalbouw.nl",
        subject: "Work completion sign-off and NEN 1010 certification",
        snippet: "Attached is the sign-off certificate for the main fuse box overhaul.",
        body: "Hi Harjot,\n\nPlease find attached the signed NEN 1010 certificate for the fuse box inspection completed yesterday.\n\nKevin Chahal",
        date: "03 Nov 2026",
        time: "03 Nov",
        hasAttachments: true,
        category: "maintenance",
      },
    ],
    whatsappMessages: [
      {
        id: "wa-kc-1",
        sender: "tenant",
        text: "Morning Harjot, team is en-route for the fuse board service.",
        date: "Yesterday",
        time: "08:15",
        status: "read",
      },
    ],
  },
  {
    id: "c-2",
    name: "Jan Vermeer",
    avatarUrl: "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?w=200&auto=format&fit=crop&q=80",
    companyName: "Vermeer Loodgieters",
    category: "contractor",
    tradeOrRole: "Plumber / Loodgieter",
    phone: "+31 6 22 41 89 00",
    email: "spoed@vermeerloodgieters.nl",
    address: "Westergasfabriek 18, 1014 DC Amsterdam",
    preferredChannel: "whatsapp",
    status: "active",
    slaAvgHours: 2.2,
    openTicketsCount: 0,
    rating: 4.8,
    notes: "Top plumbing specialist for canal house drain blockages and pipe repairs.",
    documents: [],
    leases: [],
    emails: [],
    whatsappMessages: [],
  },
];
