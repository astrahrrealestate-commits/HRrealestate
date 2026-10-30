# Super Agent Full Connection & UI Implementation Plan

> **Branch:** `experiment-superagent-ui` (All changes isolated and safe)  
> **Design Philosophy:** Minimalist, clean, executive-grade, mobile-responsive, no emojis, professional Lucide icons only, smooth hardware-accelerated transitions.

---

## 1. Architectural Overview & Connection Map

The goal is to connect the Super Agent engine directly into the frontend experience so the owner can interact naturally, see real-time execution steps, inspect an in-chat visual preview of the generated work (e.g. drafted WhatsApp/Email messages), and approve or dispatch with 1 click.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Next.js Frontend                                │
│                                                                        │
│  [ TopCommandBar ] ──(Smooth Slide/Fade Transition)──► [ AskEstateOSPanel ]
│                                                               │        │
│                                            (Streams / Renders)│        │
│                                                               ▼        │
│                                                ┌─────────────────────┐ │
│                                                │ Step Checklist      │ │
│                                                │ Mini Preview Canvas │ │
│                                                │ [Accept & Send]     │ │
│                                                └─────────────────────┘ │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP POST / SSE
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI & Agent Engine                          │
│                                                                        │
│  [ POST /api/agent/ask ] ──► [ OWNER_QA / CONCIERGE Planner ]          │
│                                             │                          │
│                                             ▼                          │
│                                [ DB Read / Context Match ]             │
│                                (Cases, Units, Approvals)               │
│                                             │                          │
│                                             ▼                          │
│                                [ Action / Draft Synthesizer ]          │
│                                             │                          │
│                                             ▼                          │
│                          Returns Clean JSON + Preview Schema           │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. API Contracts & Data Flow

### A. Endpoint: `POST /api/agent/ask` (Extended)
We reuse and enhance the active endpoint in `app/api/agent/routes.py` without breaking existing clients.

#### Request Payload:
```json
{
  "query": "Draft a WhatsApp reply to Pieter about the water leak at Keizersgracht",
  "context": "Inbox"
}
```

#### Enhanced Response Payload:
```json
{
  "answer": "I have drafted a WhatsApp response for the water leak at Keizersgracht 42-A.",
  "caseRefs": ["#01a1"],
  "executedAt": "2026-10-21T18:00:00Z",
  "steps": [
    "Identified case #01a1 (Keizersgracht 42-A)",
    "Matched recipient (+919456916996)",
    "Generated emergency repair response in Dutch"
  ],
  "previewCard": {
    "type": "draft_message",
    "channel": "whatsapp",
    "recipient": "+919456916996",
    "unitLabel": "Keizersgracht 42-A",
    "subject": null,
    "body": "Beste bewoner, we hebben Harjot direct op de hoogte gebracht...",
    "actionId": "01a1549c-76f8-7262-964c-22bd4072d155",
    "caseId": "01a1549c-5871-7fe1-9849-ee4f9e42c2ca"
  }
}
```

### B. Endpoint: `POST /api/inbox/threads/{id}/approve-draft` (Existing)
Triggered directly from the mini preview card when clicking `Accept and send`.
- Dispatches via Meta Cloud API or Gmail.
- Returns status `delivered`.

---

## 3. Frontend UI/UX Specifications

### A. Smooth Panel Transition
- **Desktop**: Slide-over drawer anchored to the right side (width: `440px` on desktop, `100vw` on mobile).
- **Animation**: CSS `cubic-bezier(0.16, 1, 0.3, 1)` easing (Apple/Linear standard) with a 250ms duration.
- **Backdrop**: Subtle dark blur backdrop (`backdrop-blur-sm bg-black/20`).

### B. Clean & Minimalist Visual Language
- **No Emojis**: Replace all informal symbols with crisp Lucide monochrome vector icons:
  - Checkstep: `<CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />`
  - Processing: `<Loader2 className="w-3.5 h-3.5 animate-spin text-zinc-400" />`
  - Channel Badge: Small `<MessageSquare />` or `<Mail />` vector tag.
  - Action trigger: `<SendHorizontal className="w-3.5 h-3.5" />`
- **Typography & Colors**:
  - Dark/glassmorphic slate border (`border-zinc-200 dark:border-zinc-800`).
  - Crisp Inter font weights (medium labels, muted subtitles).
  - High whitespace contrast to prevent visual clutter.

### C. The Mini Preview Canvas (Inside the Chat Bubble)
Instead of forcing the user into a separate page, render a focused workspace card directly inside the agent's turn:
1. **Header Row**:
   - Channel pill (`WhatsApp` in subtle emerald tone).
   - Recipient and Unit address (`+919456916996 • Keizersgracht 42-A`).
2. **Body Frame**:
   - Monospace/clean card displaying the formatted drafted message.
3. **Bottom Controls (Single row, minimal buttons)**:
   - Primary: `[Accept and send]` (Clean solid button).
   - Secondary: `[Edit]` (Subtle ghost button).
   - Link: `[Open in Inbox]` (Small arrow icon link for deep inspection).

### D. Mobile Responsiveness
- On screens `< 640px` (iPhone/Android):
  - The drawer expands to full width (`w-full inset-0`).
  - Font size on inputs stays at minimum `16px` to prevent iOS zoom-in glitch.
  - Action buttons expand to comfortable tap targets (`min-h-[44px]`).

---

## 4. File Modification Scope

### Backend:
1. `app/api/agent/routes.py`:
   - Enhance `ask_agent` to assemble `steps` and `previewCard` when a query references drafting, viewing, or searching cases.

### Frontend:
1. `frontend/src/lib/api.ts`:
   - Update `AskAgentResponse` interface to include `steps?: string[]` and `previewCard?: PreviewCardData`.
2. `frontend/src/components/assistant/AskEstateOSPanel.tsx`:
   - Refactor UI container for smooth spring slide-in transition.
   - Add the `<MiniPreviewCard />` component for rendered drafts and case previews.
   - Clean up existing badges to eliminate all emojis and redundant button clutter.
3. `frontend/src/components/layout/TopCommandBar.tsx`:
   - Ensure the trigger button opens the panel with seamless transition on all viewport sizes.

---

## 5. Execution Steps
1. Verify `experiment-superagent-ui` branch is clean.
2. Update backend schema and response formatter in `app/api/agent/routes.py`.
3. Update frontend API types in `frontend/src/lib/api.ts`.
4. Refactor and style `AskEstateOSPanel.tsx` with smooth transitions and the Mini Preview Canvas.
5. Test live in browser on both desktop and mobile viewports.
