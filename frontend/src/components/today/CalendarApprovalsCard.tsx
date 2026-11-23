"use client";

import React, { useEffect, useState, useMemo } from "react";
import {
  Calendar,
  Clock,
  MapPin,
  Wrench,
  KeyRound,
  Check,
  CheckCircle2,
  Loader2,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  ClipboardCheck,
  Eye,
  CalendarCheck2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock, formatWeekdayDate, localDayNumber } from "@/lib/clock";
import { useLanguage } from "@/context/LanguageContext";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { IncomingInvitesSection } from "@/components/today/IncomingInvitesSection";
import {
  CalendarEvent,
  getCalendarEvents,
  approveCalendarEvent,
} from "@/lib/api";

export interface CalendarApprovalsCardProps {
  initialEvents?: CalendarEvent[];
  onApproveSuccess?: (eventId: string, title: string) => void;
  onInviteAnswered?: (title: string, response: "accepted" | "declined" | "tentative") => void;
  className?: string;
}

const DEFAULT_TOP_N = 3;

function formatSlot(startIso: string, endIso: string): string {
  try {
    const start = new Date(startIso);
    const end = new Date(endIso);
    const now = new Date();

    const ahead = localDayNumber(start) - localDayNumber(now);
    const isToday = ahead === 0;
    const isTomorrow = ahead === 1;

    const dateLabel = isToday
      ? "Today"
      : isTomorrow
      ? "Tomorrow"
      : formatWeekdayDate(start);

    const startTime = formatClock(start);
    const endTime = formatClock(end);

    return `${dateLabel} · ${startTime} – ${endTime}`;
  } catch {
    return "";
  }
}

export function CalendarApprovalsCard({
  initialEvents,
  onApproveSuccess,
  onInviteAnswered,
  className,
}: CalendarApprovalsCardProps) {
  const { t } = useLanguage();
  const [events, setEvents] = useState<CalendarEvent[]>(initialEvents || []);
  const [isLoading, setIsLoading] = useState<boolean>(!initialEvents);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [filterMode, setFilterMode] = useState<"pending" | "all">("pending");

  useEffect(() => {
    if (initialEvents && initialEvents.length > 0) return;
    let isMounted = true;
    setIsLoading(true);

    getCalendarEvents()
      .then((res) => {
        if (!isMounted) return;
        setEvents(res.events || []);
      })
      .catch((err) => {
        console.warn("Error loading calendar events:", err);
      })
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [initialEvents]);

  const pendingEvents = useMemo(
    () => events.filter((e) => e.status === "proposed"),
    [events]
  );

  const displayedEvents = useMemo(() => {
    const list = filterMode === "pending" ? pendingEvents : events;
    return isExpanded ? list : list.slice(0, DEFAULT_TOP_N);
  }, [events, pendingEvents, filterMode, isExpanded]);

  const hasMoreThanTopN = (filterMode === "pending" ? pendingEvents : events).length > DEFAULT_TOP_N;

  const handleApprove = async (event: CalendarEvent) => {
    setApprovingId(event.id);
    const prevStatus = event.status;

    // Optimistic UI state update
    setEvents((prev) =>
      prev.map((e) =>
        e.id === event.id
          ? {
              ...e,
              status: "confirmed",
              confirmedAt: new Date().toISOString(),
            }
          : e
      )
    );

    try {
      const res = await approveCalendarEvent(event.id);
      if (res.ok) {
        if (res.event) {
          setEvents((prev) =>
            prev.map((e) => (e.id === event.id ? res.event! : e))
          );
        }
        onApproveSuccess?.(event.id, event.title);
      } else {
        // Rollback on rejection
        setEvents((prev) =>
          prev.map((e) => (e.id === event.id ? { ...e, status: prevStatus } : e))
        );
      }
    } catch (err) {
      console.error("Failed to approve calendar event:", err);
      setEvents((prev) =>
        prev.map((e) => (e.id === event.id ? { ...e, status: prevStatus } : e))
      );
    } finally {
      setApprovingId(null);
    }
  };

  const getEventTypeBadge = (eventType: string) => {
    switch (eventType) {
      case "contractor_repair":
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] px-2 py-0.5 rounded border border-[var(--line)]">
            <Wrench className="w-3 h-3 text-[var(--accent-ink)] shrink-0 stroke-[1.5]" />
            {t("Contractor Repair")}
          </span>
        );
      case "inspection":
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] px-2 py-0.5 rounded border border-[var(--line)]">
            <ClipboardCheck className="w-3 h-3 text-sky-600 dark:text-sky-400 shrink-0 stroke-[1.5]" />
            {t("Inspection")}
          </span>
        );
      case "viewing":
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] px-2 py-0.5 rounded border border-[var(--line)]">
            <Eye className="w-3 h-3 text-violet-600 dark:text-violet-400 shrink-0 stroke-[1.5]" />
            {t("Viewing")}
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-[var(--ink)] bg-[var(--selected)] px-2 py-0.5 rounded border border-[var(--line)]">
            <Calendar className="w-3 h-3 text-[var(--ink-2)] shrink-0 stroke-[1.5]" />
            {t("Visit")}
          </span>
        );
    }
  };

  return (
    <section
      id="section-calendar-approvals"
      data-testid="calendar-approvals-card"
      className={cn(
        "bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden transition-all",
        className
      )}
    >
      {/* Header */}
      <div className="px-4 sm:px-5 py-3 border-b border-[var(--line)] bg-[var(--pane)] flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <SectionHeader
            title={t("Visits & Calendar Approvals")}
            count={pendingEvents.length > 0 ? `${pendingEvents.length} ${t("Pending Approval")}` : undefined}
          />
        </div>

        {/* View mode toggle */}
        <div className="flex items-center gap-1 bg-[var(--bg)]/80 p-0.5 rounded-lg border border-[var(--line)] text-xs">
          <button
            type="button"
            onClick={() => setFilterMode("pending")}
            className={cn(
              "px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer",
              filterMode === "pending"
                ? "bg-[var(--pane)] text-[var(--ink)] shadow-xs"
                : "text-[var(--ink-3)] hover:text-[var(--ink)]"
            )}
          >
            {t("Pending")} ({pendingEvents.length})
          </button>
          <button
            type="button"
            onClick={() => setFilterMode("all")}
            className={cn(
              "px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer",
              filterMode === "all"
                ? "bg-[var(--pane)] text-[var(--ink)] shadow-xs"
                : "text-[var(--ink-3)] hover:text-[var(--ink)]"
            )}
          >
            {t("All")} ({events.length})
          </button>
        </div>
      </div>

      <IncomingInvitesSection onAnswered={onInviteAnswered} />

      {/* Content list */}
      {isLoading ? (
        <div className="p-6 space-y-3">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="h-20 bg-[var(--bg)]/40 rounded-lg animate-pulse border border-[var(--line)]"
            />
          ))}
        </div>
      ) : displayedEvents.length === 0 ? (
        <div className="p-8 text-center bg-[var(--pane)] space-y-2">
          <CalendarCheck2 className="w-7 h-7 text-emerald-600 dark:text-emerald-400 mx-auto stroke-[1.5]" />
          <p className="text-sm font-semibold text-[var(--ink)]">
            {t("All visits approved and synced")}
          </p>
          <p className="text-xs text-[var(--ink-3)] max-w-md mx-auto">
            {t("No appointments or contractor visits currently require your sign-off.")}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-[var(--line)]">
          {displayedEvents.map((evt) => {
            const isConfirmed = evt.status === "confirmed";
            const isApproving = approvingId === evt.id;
            const attendeeName =
              evt.attendees && evt.attendees.length > 0
                ? evt.attendees[0].displayName || evt.attendees[0].email
                : null;

            return (
              <div
                key={evt.id}
                className="p-4 sm:px-5 hover:bg-[var(--selected)]/30 transition-colors space-y-3"
              >
                {/* Row Header: Tags & Time */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    {getEventTypeBadge(evt.eventType)}

                    {isConfirmed ? (
                      <span className="inline-flex items-center gap-1 font-mono text-[10.5px] font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
                        <CheckCircle2 className="w-3 h-3 stroke-[1.5]" />
                        {t("Synced to Google Calendar")}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 font-mono text-[10.5px] font-medium text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded-full">
                        <Clock className="w-3 h-3 stroke-[1.5]" />
                        {t("Pending Approval")}
                      </span>
                    )}
                  </div>

                  {/* Monospace Time */}
                  <div className="font-mono text-xs tabular-nums text-[var(--ink-2)] flex items-center gap-1.5 bg-[var(--bg)] px-2.5 py-1 rounded-md border border-[var(--line)]">
                    <Calendar className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0 stroke-[1.5]" />
                    <span>{formatSlot(evt.startTime, evt.endTime)}</span>
                  </div>
                </div>

                {/* Title & Location */}
                <div className="space-y-1">
                  <h4 className="text-[13.5px] font-semibold text-[var(--ink)] tracking-tight">
                    {evt.title}
                  </h4>
                  {evt.location && (
                    <div className="flex items-center gap-1.5 text-xs text-[var(--ink-2)]">
                      <MapPin className="w-3.5 h-3.5 text-[var(--ink-3)] shrink-0 stroke-[1.5]" />
                      <span className="font-medium">{evt.location}</span>
                    </div>
                  )}
                </div>

                {/* Operational Details Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs bg-[var(--bg)]/60 border border-[var(--line)] rounded-lg p-2.5">
                  {attendeeName && (
                    <div className="flex items-center gap-1.5 text-[var(--ink-2)] min-w-0">
                      <span className="text-[var(--ink-3)]">Contractor:</span>
                      <span className="font-medium text-[var(--ink)] truncate">
                        {attendeeName}
                      </span>
                    </div>
                  )}

                  {evt.lockboxCode && (
                    <div className="flex items-center gap-1.5 text-[var(--ink-2)] min-w-0">
                      <KeyRound className="w-3.5 h-3.5 text-[var(--accent-ink)] shrink-0 stroke-[1.5]" />
                      <span className="font-mono text-[11.5px] text-[var(--ink)] truncate">
                        {evt.lockboxCode}
                      </span>
                    </div>
                  )}

                  {evt.description && (
                    <div className="col-span-1 sm:col-span-2 text-[11.5px] text-[var(--ink-3)] line-clamp-2 pt-0.5 border-t border-[var(--line)]/50">
                      {evt.description}
                    </div>
                  )}
                </div>

                {/* Footer Action Bar */}
                <div className="flex items-center justify-between gap-3 pt-1">
                  <span className="font-mono text-[10.5px] text-[var(--ink-3)]">
                    {isConfirmed
                      ? "1-click confirmed and synced to Google Calendar"
                      : "Awaiting owner 1-click confirmation"}
                  </span>

                  <div className="flex items-center gap-2">
                    {isConfirmed ? (
                      <div className="flex items-center gap-2">
                        {evt.htmlLink ? (
                          <a
                            href={evt.htmlLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-[var(--accent-ink)] hover:underline font-medium"
                          >
                            <span>Open in Calendar</span>
                            <ExternalLink className="w-3 h-3 stroke-[1.5]" />
                          </a>
                        ) : (
                          <span className="text-xs text-emerald-700 dark:text-emerald-400 font-medium inline-flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5 stroke-[1.5]" />
                            {t("Confirmed")}
                          </span>
                        )}
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleApprove(evt)}
                        disabled={isApproving}
                        className={cn(
                          "inline-flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all shadow-xs",
                          "bg-[var(--ink)] hover:bg-[var(--ink)]/90 text-white disabled:opacity-50"
                        )}
                      >
                        {isApproving ? (
                          <>
                            <Loader2 className="w-3.5 h-3.5 animate-spin stroke-[1.5]" />
                            <span>Syncing...</span>
                          </>
                        ) : (
                          <>
                            <Check className="w-3.5 h-3.5 stroke-[2]" />
                            <span>{t("Approve & Add to Calendar")}</span>
                          </>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Show more toggle if more than Top N */}
      {hasMoreThanTopN && (
        <div className="p-2 border-t border-[var(--line)] bg-[var(--pane)] text-center">
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="inline-flex items-center gap-1 text-xs text-[var(--ink-2)] hover:text-[var(--ink)] font-medium py-1 px-3 rounded cursor-pointer transition-colors"
          >
            <span>
              {isExpanded
                ? "Show less"
                : `Show all ${(filterMode === "pending" ? pendingEvents : events).length} visits`}
            </span>
            {isExpanded ? (
              <ChevronUp className="w-3.5 h-3.5 stroke-[1.5]" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 stroke-[1.5]" />
            )}
          </button>
        </div>
      )}
    </section>
  );
}
