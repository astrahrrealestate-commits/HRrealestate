export interface SettingItem {
  id: string;
  title: string;
  description: string;
  valueType: "toggle" | "select" | "text";
  currentValue: string | boolean;
  options?: string[];
}

export interface SettingGroup {
  id: string;
  title: string;
  description: string;
  settings: SettingItem[];
}

export const SETTING_GROUPS: SettingGroup[] = [
  {
    id: "notifications",
    title: "Notifications & Alerts",
    description: "Emergency alerts, SMS escalation rules, and daily digest schedules.",
    settings: [
      {
        id: "s-emergency-sms",
        title: "Emergency SMS Overrides",
        description: "Send direct SMS to Harjot when a Short Circuit or Gas Leak emergency arrives.",
        valueType: "toggle",
        currentValue: true,
      },
      {
        id: "s-digest-time",
        title: "Daily Executive Briefing Delivery",
        description: "Scheduled time for Today briefing generation and sync.",
        valueType: "select",
        currentValue: "07:30 CET",
        options: ["07:00 CET", "07:30 CET", "08:00 CET", "09:00 CET"],
      },
      {
        id: "s-quiet-hours",
        title: "Contractor Quiet Hours Auto-Response",
        description: "Queue non-urgent contractor dispatch requests received after 20:00 until 07:30.",
        valueType: "toggle",
        currentValue: true,
      },
    ],
  },
  {
    id: "ai-governance",
    title: "AI Autonomy & Thresholds",
    description: "Guardrails for automated contractor dispatches and tenant communications.",
    settings: [
      {
        id: "s-auto-dispatch-cap",
        title: "Emergency Auto-Dispatch PO Cap",
        description: "Maximum contractor work order budget the AI can pre-approve autonomously.",
        valueType: "select",
        currentValue: "€ 650,-",
        options: ["€ 350,-", "€ 500,-", "€ 650,-", "€ 1.000,-"],
      },
      {
        id: "s-draft-language",
        title: "Multi-lingual Detection & Translation",
        description: "Automatically translate incoming Dutch messages and draft replies in detected native language.",
        valueType: "toggle",
        currentValue: true,
      },
      {
        id: "s-require-confirmation",
        title: "Require Human Approval on Eviction or Rent Notices",
        description: "Enforce owner review before sending overdue reminders beyond 14 days grace period.",
        valueType: "toggle",
        currentValue: true,
      },
    ],
  },
  {
    id: "channels",
    title: "Connected Channels & Sync",
    description: "Status and webhooks for WhatsApp Business API, Gmail, and ING Bank feeds.",
    settings: [
      {
        id: "s-wa-sync",
        title: "Meta WhatsApp Cloud API Webhook",
        description: "Real-time bidirectional message ingestion for +31 20 000 0001.",
        valueType: "toggle",
        currentValue: true,
      },
      {
        id: "s-gmail-sync",
        title: "Google Workspace Gmail Push Notifications",
        description: "OAuth 2.0 connected & synced to tyagisurya.04@gmail.com.",
        valueType: "toggle",
        currentValue: true,
      },
      {
        id: "s-ing-feed",
        title: "ING Corporate CAMT.053 Bank Feed",
        description: "Nightly automated transaction sync at 04:00 CET.",
        valueType: "toggle",
        currentValue: true,
      },
    ],
  },
  {
    id: "portfolio",
    title: "Portfolio & Default Terms",
    description: "Standard Dutch residential lease templates, lockbox protocols, and municipal indexing.",
    settings: [
      {
        id: "s-lease-model",
        title: "Default Tenancy Agreement Template",
        description: "Standard model applied to new lease generation.",
        valueType: "select",
        currentValue: "ROZ Model 2017 (Woonruimte)",
        options: ["ROZ Model 2017 (Woonruimte)", "ROZ Model 2024", "Diplomatic Clause Template"],
      },
      {
        id: "s-lockbox-retention",
        title: "Lockbox PIN Auto-Rotation",
        description: "Rotate unit key lockbox code automatically 48 hours after contractor checkout.",
        valueType: "toggle",
        currentValue: false,
      },
    ],
  },
  {
    id: "persona",
    title: "Draft Persona",
    description: "The writing persona (markdown) the draft agent uses when it replies as Harjot.",
    settings: [],
  },
  {
    id: "memory-rules",
    title: "AI Standing Rules & Memory",
    description: "T5 standing memory rules, contractor ceilings, and tenant communication preferences.",
    settings: [],
  },
];
