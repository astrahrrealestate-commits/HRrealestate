# EstateOS User Stories & Capabilities Roadmap (Stories #1 - #20)

This document tracks the comprehensive implementation status, existing architecture, and future development roadmap for the 20 primary User Stories from the **HR Real Estate - EstateOS Project Workbook**.

---

## Executive Summary Matrix

| # | Category | User Story Summary | Current Status | Completion % |
|---|---|---|---|---|
| **1** | Email & WhatsApp | AI continuously prioritizes incoming email & separates low-value noise | **Solved** | 90% |
| **2** | Email & WhatsApp | Omnichannel WhatsApp & email ingestion with full audit trail | **Solved** | 95% |
| **3** | Email & WhatsApp | Hold back sensitive replies (legal, disputes, arrears) for owner review | **Solved** | 90% |
| **4** | Email & WhatsApp | Draft-first AI replies with human-in-the-loop approval guardrails | **Solved** | 90% |
| **5** | Tasks & CRM | Historical migration of open actions from WhatsApp, Sheets, & email into CRM | **Not Solved** | 15% |
| **6** | Tasks & CRM | Auto-create structured tasks/cases from incoming communications | **Solved** | 85% |
| **7** | Tasks & CRM | Proactive automated chasing for missed follow-ups (contractors, tenant replies) | **Partially Solved** | 35% |
| **8** | Documents & Drive | Google Drive as single business document source of truth with AI organization | **Not Solved** | 20% |
| **9** | Documents & Drive | AI brings consistent hierarchical folder ordering to Google Drive | **Not Solved** | 15% |
| **10** | Documents & Drive | Plain-language Q&A assistant with citations from Drive & communications | **Partially Solved** | 50% |
| **11** | Maintenance | Auto-classification of repairs by property, urgency, and task assignment | **Solved** | 85% |
| **12** | Maintenance | Automated contractor task creation, quotation requests, & price comparison | **Not Solved** | 25% |
| **13** | Maintenance | Complete end-to-end repair record (photos, costs, deadlines, approvals) | **Solved** | 85% |
| **14** | Inspections | Mobile-friendly on-site inspection app (photos, meters, defects, signatures) | **Not Solved** | 20% |
| **15** | Inspections | AI summarizes inspection findings and creates follow-up work orders | **Partially Solved** | 30% |
| **16** | Rent & Arrears | Auto-detect overdue rent and trigger progressive reminder cadences | **Partially Solved** | 40% |
| **17** | Rent & Arrears | Clear visual arrears dashboard with tracked tasks per case | **Solved** | 80% |
| **18** | Rent & Arrears | Explicit human approval required for payment plans, legal notices, & evictions | **Solved** | 95% |
| **19** | Financial Visibility | Automated rent roll, occupancy, capex, and cash-flow reporting | **Solved** | 80% |
| **20** | Financial Visibility | Proactive deadline tracking & reminders (mortgages, taxes, indexation) | **Not Solved** | 25% |

---

## Detailed Story Breakdowns

---

### Category 1: Email and WhatsApp Communication

#### Story 1: Intelligent Email Triage & Noise Filtering
> *"As the owner, I want AI to continuously read and prioritise incoming business email, so that I can separate actionable items from low-value traffic without reading everything myself."*
- **Status:** **Solved (90%)**
- **What is built:**
  - Gmail sync worker (`app/ingestion/gmail_sync.py`) ingests raw emails via Pub/Sub or polling.
  - LLM pipeline filters out promotional newsletters, job notifications (Glassdoor, LinkedIn, Naukri), and system digests.
  - Actionable items are classified into categories (`maintenance`, `financial`, `general`) and urgency tiers (`emergency`, `urgent`, `normal`).
  - Frontend displays items separated into **"Needs you"** and priority queues.
- **Future Work:**
  - Dynamic user-configurable spam/digest whitelist in the UI Settings.

#### Story 2: Omnichannel Capture with Full Audit Trail
> *"As the owner, I want AI to capture relevant actions from WhatsApp as well as email, with a full audit trail, so that nothing important is missed because it arrived on the 'wrong' channel."*
- **Status:** **Solved (95%)**
- **What is built:**
  - WhatsApp webhook via Hookdeck (`app/api/webhooks/whatsapp.py`) receives live messages.
  - Full relational audit trail in PostgreSQL: `raw_events` -> `messages` -> `cases` -> `case_links` -> `actions` -> `approvals`.
  - Proven with live WhatsApp test (`+919456916996`) for Keizersgracht water leak.
- **Future Work:**
  - Automatic entity resolution to link newly encountered phone numbers to properties/units without manual tenant database pre-population.

#### Story 3: Guardrail Holdbacks on Sensitive & Legal Topics
> *"As the owner, I want AI to hold back any reply involving material legal matters, disputes or settlements, tenancy termination, sensitive arrears escalation, material financial commitments, financing or investment communication, acquisitions or sales, tax matters, reputationally sensitive topics, or anything where its confidence is low, and bring these to me for review before anything is sent."*
- **Status:** **Solved (90%)**
- **What is built:**
  - `app/pipeline/injection_scan.py` and `app/pipeline/output_guard.py` scan proposed responses.
  - High-risk categories cannot be dispatched autonomously; they require explicit human approval via the `approvals` table.
- **Future Work:**
  - Add explicit "Confidence Score" and "Legal Risk" banner badges to the triage card in the frontend UI.

#### Story 4: Draft-First AI Replies (Progressive Autonomy)
> *"As the owner, I want AI to draft replies on my behalf rather than send them automatically at first, moving to automatic sending only progressively, one category of message at a time, under guardrails I set."*
- **Status:** **Solved (90%)**
- **What is built:**
  - The AI outputs multiple response variants (`Draft 1`, `Draft 2`) stored in `actions.payload`.
  - Frontend composer provides an **`[Accept and send]`**, **`Edit`**, and **`Reject`** workflow. No automated outgoing dispatch occurs without user consent.
- **Future Work:**
  - Add an "Autonomous Threshold Slider" in Settings to permit automatic dispatch only for verified routine queries (e.g., standard FAQ, rent receipt confirmation).

---

### Category 2: Tasks, Follow-ups, and Single Source of Truth

#### Story 5: Historical Data Migration into CRM
> *"As the owner, I want my existing open actions from email, WhatsApp, Sheets and notes migrated into one AI agent CRM, so that nothing from before go-live is lost."*
- **Status:** **Not Solved (15%)**
- **What is built:**
  - Database schema supports cases, notes, contacts, and properties.
- **Future Work:**
  - Build a CSV/Google Sheets one-click import tool (`POST /api/v1/import/sheets`).
  - Historical Gmail backfill script to ingest past threads from the last 6 months.

#### Story 6: Structured Task Generation from Communications
> *"As the owner, I want AI to automatically create structured tasks from new communications and documents, so that follow-ups stop living only in my inbox, WhatsApp and personal notes."*
- **Status:** **Solved (85%)**
- **What is built:**
  - Incoming communications are automatically converted to actionable `Case` records with summaries, categories, urgency levels, and generated action proposals.
- **Future Work:**
  - Add manual "Convert to Task" button in the conversation thread view for unstructured messages.

#### Story 7: Automated Follow-Up Chaser Worker
> *"As the owner, I want AI to track and chase the follow-ups that are most commonly missed — contractor and adviser responses, maintenance actions, tenant commitments, arrears, municipal or permit actions, financing requests, document requests, due-diligence questions and inspections — until each one is closed."*
- **Status:** **Partially Solved (35%)**
- **What is built:**
  - Cases retain state (`waiting_on_owner`, `waiting_on_tenant`, `waiting_on_contractor`).
- **Future Work:**
  - Implement a DBOS background scheduled cron/sweep (`app/workflows/sweeps.py`) that checks for cases open > 48 hours without inbound response and drafts follow-up nudges.

---

### Category 3: Document Management & Google Drive

#### Story 8: Google Drive as Single Source of Truth
> *"As the owner, I want Google Drive to remain the single business document base, with AI keeping it organised, so that local or personal storage never becomes a second source of truth."*
- **Status:** **Not Solved (20%)**
- **What is built:**
  - S3 and local storage adapters exist (`app/storage/`); Google Drive provider is currently stubbed/fake.
- **Future Work:**
  - Connect live Google Drive API with OAuth service account to persist uploaded documents directly to Drive folders.

#### Story 9: Automated Drive Hierarchy & Organization
> *"As the owner, I want AI to bring consistent order to a Drive that is only partly organised today, so that it can support the growth I expect in the portfolio."*
- **Status:** **Not Solved (15%)**
- **What is built:**
  - Architectural blueprints exist in `app/workflows/documents.py`.
- **Future Work:**
  - Implement an automated document classifier: incoming invoices, leases, and inspection photos automatically move to `/EstateOS/{Property_Address}/{Category}/{Year}/`.

#### Story 10: Natural Language Q&A Assistant with Citations
> *"As the owner, I want to ask the system a plain-language question about a property, tenant, financing matter, project or transaction and get an answer drawn from the relevant Drive documents and communications, with source references, so that the answer is auditable and I do not have to search for it myself."*
- **Status:** **Partially Solved (50%)**
- **What is built:**
  - Super Agent Concierge backend (`app/api/v1/agent.py`, `app/pipeline/concierge*`) and `AskEstateOSPanel.tsx` UI drawer exist.
  - The Concierge can answer queries against database state.
- **Future Work:**
  - Connect RAG vector search over Google Drive PDFs (lease agreements, insurance policies) to return exact document citations and page numbers.

---

### Category 4: Maintenance and Repairs

#### Story 11: Repair Request Auto-Classification & Urgency
> *"As the owner, I want a repair request to be automatically classified by property, tenant and urgency, turned into a task with an owner, and tracked from first report through to tenant confirmation and closure, so that handling is no longer mostly manual."*
- **Status:** **Solved (85%)**
- **What is built:**
  - Real-world verified with water leak message: classified as `maintenance`, `emergency`, with structured summary and assigned next steps.
- **Future Work:**
  - Automate the final tenant sign-off loop (e.g. sending automated message: *"Has your leak been resolved? Reply YES to close ticket"*).

#### Story 12: Automated Contractor Quotations & Assignment
> *"As operations support, I want AI to create and assign contractor tasks, request or prepare quotations, chase responses, and compare scope and price within my approval thresholds, so that contractor coordination is no longer manual relationship management."*
- **Status:** **Not Solved (25%)**
- **What is built:**
  - Schema has contractor and quote placeholders.
- **Future Work:**
  - Create a `contractors` directory table grouped by trade (plumbing, electrical, HVAC).
  - Enable AI to draft quote requests directly to 2-3 preferred vendors when a ticket is opened.

#### Story 13: Complete End-to-End Repair Audit Trail
> *"As the owner, I want every repair ticket to keep a complete record — communications, photos, owner, contractor, cost, deadlines, status and completion confirmation — with automatic chasing of overdue steps and escalation of exceptions, so that I can see any case end to end without reconstructing it myself."*
- **Status:** **Solved (85%)**
- **What is built:**
  - Centralized `/maintenance` view and unified `Case` database model linking messages, drafts, timestamps, and history in one timeline.
- **Future Work:**
  - Add invoice/cost tracking directly to the case timeline.

---

### Category 5: Inspections

#### Story 14: Mobile-Friendly On-Site Inspection Capture
> *"As operations support, I want a mobile-friendly way to capture photos, video, notes, meter readings, defects and signatures during an inspection, so that findings are recorded on site rather than written up later."*
- **Status:** **Not Solved (20%)**
- **What is built:**
  - Responsive web design for the main dashboard.
- **Future Work:**
  - Build a dedicated mobile inspection flow (`/inspections/new`) with camera capture, meter photo upload, and canvas signature capture.

#### Story 15: AI-Powered Inspection Report Summaries
> *"As the owner, I want AI to summarise inspection findings, attach the evidence to the correct property and unit, and create follow-up tasks automatically, while leaving final liability and damage decisions to a human reviewer."*
- **Status:** **Partially Solved (30%)**
- **What is built:**
  - Gemini multimodal API is wired into backend, capable of analyzing image attachments.
- **Future Work:**
  - Ingestion endpoint to convert an inspection report into discrete defect tasks with photo attachments.

---

### Category 6: Rent and Arrears

#### Story 16: Automated Overdue Rent Detection & Progressive Chasing
> *"As the owner, I want AI to automatically detect late or unpaid rent, send standard reminders, and escalate by age and amount, so that arrears are never followed up manually again."*
- **Status:** **Partially Solved (40%)**
- **What is built:**
  - Data models track rent schedules and payment records.
- **Future Work:**
  - Scheduled worker checking bank transactions against rent rolls on the 1st, 5th, and 10th of each month, drafting reminder notices automatically.

#### Story 17: Visual Arrears Dashboard & Exposure Tracking
> *"As the owner, I want a clear arrears dashboard with a task created for each case, so that I can see my exposure at a glance."*
- **Status:** **Solved (80%)**
- **What is built:**
  - Financial overview cards on the `/money` page and dashboard deck show tenant arrears and late payment counts.
- **Future Work:**
  - Direct 1-click link from an arrears stat card to open a pre-drafted WhatsApp reminder.

#### Story 18: Mandatory Approval Gate on Legal Escalations & Evictions
> *"As the owner, I want payment arrangements, legal escalation and tenancy termination to always require my explicit approval, even though routine reminders can be automated."*
- **Status:** **Solved (95%)**
- **What is built:**
  - Rigorous guardrail in `app/sender/tenant_gate.py` and `approvals` system. Any formal legal notice or eviction demand strictly halts and requires explicit owner signature/click.
- **Future Work:**
  - Audit logging of IP address and timestamp for legal approvals.

---

### Category 7: Financial Visibility and Deadlines

#### Story 19: Unified Real Estate Portfolio Financial Cockpit
> *"As the owner, I want automatic reporting of rent roll, expected versus received rent, arrears by tenant and unit with ageing, occupancy and vacancy, property-level income and major costs, upcoming indexations, maintenance and capex spend, financing balances, interest and key dates, cash flow, and property-level KPIs where data allows, so that I have one financial picture instead of assembling it myself."*
- **Status:** **Solved (80%)**
- **What is built:**
  - Frontend `/money` and `/properties` views display rent roll, occupancy rates, net cash flow, and property-level KPIs.
- **Future Work:**
  - Real-time bank feed integration (Plaid or GoCardless API) to match live bank balance against ledger expectations.

#### Story 20: Proactive Deadline & Milestone Tracker
> *"As the owner, I want AI to track and remind me of rent and arrears actions, loan interest, repayment and refinancing dates, insurance renewals, tax and accounting deadlines, supplier invoices, deposit refunds, indexation dates and municipal charges, preparing the next action and escalating overdue or high-value items, so that no deadline is missed for lack of a reminder."*
- **Status:** **Not Solved (25%)**
- **What is built:**
  - Lease start and end dates are recorded in database tables.
- **Future Work:**
  - Build a centralized calendar & event reminder worker that creates a "Upcoming Deadlines" deck on the owner's Today dashboard 30 days ahead of renewals.

---

## Recommended Next Development Sprint

When resuming development, focus on these top 3 high-impact additions:
1. **Contractor Directory & Auto-Dispatch (Story #12)**: Add plumbing/electrical contractor records so emergency maintenance tickets can generate ready-to-send contractor quote requests.
2. **Drive RAG Integration for Concierge (Story #10)**: Connect Google Drive PDF search to the AskEstateOS panel for instant cited document answers.
3. **Automated Follow-up Sweep Worker (Story #7 & #16)**: Deploy a DBOS background cron that flags stalled maintenance tickets or late rent payments after a configurable SLA.
