import { AutonomousActionLog, ExecutiveBriefing, TriageItem } from "@/types/dashboard";

export const INITIAL_TRIAGE_ITEMS: TriageItem[] = [];

export const RECENT_AUTONOMOUS_LOGS: AutonomousActionLog[] = [];

export const DAILY_BRIEFING: ExecutiveBriefing = {
  kind: "daily",
  dayLabel: "TODAY",
  timeDelivered: "07:30 CET",
  headline: "All clear. No urgent cases or decisions waiting.",
  summarySentence: "Inbox is clear and connected channels are synced.",
  urgentCount: 0,
  decisionsCount: 0,
  overdueTasksCount: 0,
  waitingCount: 0,
  ignoredCount: 0,
  sections: [],
};

export const WEEKLY_SUMMARY: ExecutiveBriefing = {
  kind: "weekly",
  dayLabel: "EXECUTIVE RECAP",
  timeDelivered: "Friday 16:00 CET",
  headline: "Portfolio operating normally.",
  summarySentence: "Background operations completed smoothly.",
  urgentCount: 0,
  decisionsCount: 0,
  overdueTasksCount: 0,
  waitingCount: 0,
  ignoredCount: 0,
  stats: {
    casesOpened: 0,
    casesResolved: 0,
    decisionsTaken: 0,
    autonomousActions: 0,
    collectionRate: 100,
  },
  sections: [],
};
