# Frontend Tech Stack & Architecture Foundation

> **Project:** EstateOS Owner Web Dashboard  
> **Status:** Architecture Blueprint & Setup Guide  
> **Directory:** `/frontend` (Kept completely decoupled from the `/realestateos` backend repository)

---

## 1. Executive Summary & Tech Stack Choices

The EstateOS frontend is built as an **owner-first, high-density, real-time command dashboard** designed specifically for Harjot Singh and property managers. It must be blazingly fast, keyboard-navigable, completely reliable, and visually distinguished from generic AI prototypes.

### Core Technology Stack

| Layer | Technology | Version | Rationale |
| :--- | :--- | :--- | :--- |
| **Framework** | **Next.js (App Router)** | `v15.x` | Modern server components, nested layouts, optimal bundle splitting, standard production deployment. |
| **Language** | **TypeScript** | `v5.x` (Strict) | End-to-end type safety matching backend Pydantic contracts and database schemas. |
| **Styling** | **Tailwind CSS** | `v4.x` | Zero-runtime CSS, precision design tokens, arbitrary hairline borders, dark mode token maps. |
| **Component Primitives** | **Radix UI Primitives** | Latest | Unstyled, fully accessible keyboard-first accessible primitives (dialogs, dropdowns, tabs, tooltips). |
| **Iconography** | **Lucide React** | Latest | Consistent 1.5px–1.75px stroke vector icons. **Strictly zero emojis**. |
| **Client State** | **Zustand** | `v5.x` | Lightweight, non-bloated store for sidebar state, active ticket selection, and modal drawers. |
| **Server State & Cache** | **TanStack Query (React Query)** | `v5.x` | Handles optimistic UI updates (instant approve button clicks), window refetching, and cache invalidation. |
| **Data Tables** | **TanStack Table** | `v8.x` | Headless, robust table sorting, pagination, and filtering for tenants, units, and transactions. |
| **Numeric & Dates** | **date-fns** & **Intl** | Latest | Timezone-aware date formatting (`Europe/Amsterdam`), currency formatting in EUR (`€ 1.250,00`). |

---

## 2. Directory & Project Structure

The frontend application is structured inside a dedicated `frontend` folder with strict domain boundaries:

```
d:/estateos/frontend/
├── docs/                                  # Frontend architecture & design specs
│   ├── 01_TECH_STACK_AND_FOUNDATION.md
│   ├── 02_ANTI_SLOP_DESIGN_SYSTEM.md
│   ├── 03_FRONTEND_COMPONENTS_AND_BACKEND_INTEGRATION.md
│   ├── 04_COLOR_PALETTE_AND_CLEAN_UI_SPEC.md
│   └── 05_ARTIFACT_ANALYSIS_AND_BLUEPRINT.md
├── public/                                # Favicons, fonts, static branding assets
├── src/
│   ├── app/                               # Next.js 15 App Router pages & layouts
│   │   ├── layout.tsx                     # Root layout with font definitions & providers
│   │   ├── globals.css                    # Design tokens & Tailwind imports
│   │   ├── page.tsx                       # Redirects to /today
│   │   ├── (dashboard)/                   # Authenticated dashboard group layout
│   │   │   ├── layout.tsx                 # Fixed sidebar + Top bar layout wrapper
│   │   │   ├── today/                     # Main primary landing screen (The Today View)
│   │   │   │   └── page.tsx
│   │   │   ├── inbox/                     # Unified omnichannel inbox (WhatsApp, Gmail, Portal)
│   │   │   │   └── page.tsx
│   │   │   ├── tenants/                   # Tenant directory, leases, contact identities
│   │   │   │   └── page.tsx
│   │   │   ├── money/                     # Rent collections, arrears, aging buckets
│   │   │   │   └── page.tsx
│   │   │   ├── maintenance/               # Repair tickets, contractor dispatches, follow-ups
│   │   │   │   └── page.tsx
│   │   │   ├── properties/                # Units, buildings, occupancy overview
│   │   │   │   └── page.tsx
│   │   │   ├── settings/                  # Channel connections, notifications, preferences
│   │   │   │   └── page.tsx
│   │   │   └── admin/                     # System logs, DBOS queue monitor, LLM spend
│   │   │       └── page.tsx
│   ├── components/
│   │   ├── ui/                            # Low-level primitives (Button, Badge, Card, Dialog)
│   │   ├── layout/                        # Sidebar, TopBar, Breadcrumb, ServiceStatusBar
│   │   ├── today/                         # Today screen widgets (NeedsYouQueue, TriageCard, Stats)
│   │   ├── inbox/                         # ConversationList, MessageThread, DraftProposalCard
│   │   └── shared/                        # EmptyState, ErrorBoundary, KeyboardShortcutBadge
│   ├── hooks/                             # Custom hooks (useKeyboardShortcuts, useTriageQueue)
│   ├── lib/                               # Utility functions (cn, formatCurrency, formatDate)
│   ├── stores/                            # Zustand stores (useTriageStore, useSidebarStore)
│   ├── services/                          # API client & fetchers (apiClient.ts, endpoints.ts)
│   └── types/                             # TypeScript definitions (matching backend contracts)
├── .env.example
├── .env.local
├── package.json
├── tsconfig.json
└── next.config.ts
```

---

## 3. Environment & Configuration Strategy

The frontend connects to the EstateOS backend via a clean REST/WebSocket interface configured through environment variables:

```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
NEXT_PUBLIC_APP_ENV=development
NEXT_PUBLIC_DEFAULT_TIMEZONE=Europe/Amsterdam
NEXT_PUBLIC_DEFAULT_CURRENCY=EUR
```

---

## 4. Initialization & Setup Commands

To create and run this Next.js project cleanly without interactive prompt hangs:

```powershell
# Inside d:\estateos
npx -y create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --no-turbopack

# Navigate and install foundational packages
cd frontend
npm install lucide-react clsx tailwind-merge zustand @tanstack/react-query date-fns
```

---

## 5. Architectural Invariants for Frontend

1. **Decoupled from Backend Runtime:** The frontend runs as its own standalone process (e.g. `localhost:3000`), completely agnostic of Python/Docker internals. It interacts solely over standardized HTTP JSON contracts.
2. **Keyboard-First Power User Ergonomics:** Every critical owner action on the dashboard must have a hotkey:
   - `[A]`: Approve recommended action / draft
   - `[S]`: Skip or snooze current item
   - `[E]`: Edit draft
   - `[/]`: Focus global command bar
   - `[J] / [K]`: Next / Previous item in triage queue
3. **Optimistic Updates:** Tapping `Approve` removes the card from the UI immediately with a subtle visual cue while the background `POST` request fires. If the backend fails, the item rolls back with a toast notification.
