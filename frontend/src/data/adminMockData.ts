export interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: "Portfolio Owner" | "Property Manager" | "Assistant Manager" | "External Accountant";
  status: "active" | "invited" | "suspended";
  lastActive: string;
  assignedComplexes: string; // e.g. "All 3 Complexes", "Keizersgracht (42-46)"
  twoFactorEnabled: boolean;
}

export const MOCK_ADMIN_USERS: AdminUser[] = [
  {
    id: "usr-1",
    name: "Harjot Singh",
    email: "harjot@estateos.com",
    role: "Portfolio Owner",
    status: "active",
    lastActive: "Active now",
    assignedComplexes: "All 3 Complexes (110 units)",
    twoFactorEnabled: true,
  },
  {
    id: "usr-2",
    name: "Daan van Rijn",
    email: "daan.vanrijn@estateos.com",
    role: "Property Manager",
    status: "active",
    lastActive: "Today 16:40",
    assignedComplexes: "Keizersgracht & Prinsengracht",
    twoFactorEnabled: true,
  },
  {
    id: "usr-3",
    name: "Sanne Meijer",
    email: "sanne.assistant@estateos.com",
    role: "Assistant Manager",
    status: "invited",
    lastActive: "Invite sent 2 days ago",
    assignedComplexes: "Centrum Portfolio",
    twoFactorEnabled: false,
  },
  {
    id: "usr-4",
    name: "Eelco Brinkman",
    email: "brinkman@amsterdam-audit.nl",
    role: "External Accountant",
    status: "active",
    lastActive: "Yesterday 09:12",
    assignedComplexes: "Financial Ledger Read-Only",
    twoFactorEnabled: true,
  },
];
