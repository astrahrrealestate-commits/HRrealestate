/**
 * Dashboard sections a profile can be granted (the API owns the list: GET /api/v1/admin/sections) and the page route
 * each one opens. The API enforces access; this only decides what the sidebar shows and which page to refuse.
 */

export type SectionKey =
  | "dashboard"
  | "inbox"
  | "properties"
  | "tenants"
  | "contacts"
  | "maintenance"
  | "money"
  | "reports"
  | "settings";

/** The page that only team managers (superadmin) can open; it is not a grantable section. */
export const ADMIN_PATH = "/admin";

const SECTION_ROUTES: ReadonlyArray<readonly [string, SectionKey]> = [
  ["/inbox", "inbox"],
  ["/properties", "properties"],
  ["/tenants", "tenants"],
  ["/contacts", "contacts"],
  ["/maintenance", "maintenance"],
  ["/money", "money"],
  ["/reports", "reports"],
  ["/knowledge", "reports"],
  ["/settings", "settings"],
];

export const SECTION_HOME: Record<SectionKey, string> = {
  dashboard: "/",
  inbox: "/inbox",
  properties: "/properties",
  tenants: "/tenants",
  contacts: "/contacts",
  maintenance: "/maintenance",
  money: "/money",
  reports: "/reports",
  settings: "/settings",
};

/** The section a page path belongs to: "admin" for the team page, null for pages open to everyone (login, errors). */
export function sectionForPath(pathname: string): SectionKey | "admin" | null {
  if (pathname === "/") return "dashboard";
  if (pathname === ADMIN_PATH || pathname.startsWith(`${ADMIN_PATH}/`)) return "admin";
  for (const [prefix, section] of SECTION_ROUTES) {
    if (pathname === prefix || pathname.startsWith(`${prefix}/`)) return section;
  }
  return null;
}
