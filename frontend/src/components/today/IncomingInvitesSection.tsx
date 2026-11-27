"use client";

import React, { useEffect, useState } from "react";
import { Calendar, Check, ExternalLink, Loader2, MapPin, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatClock, formatDate } from "@/lib/clock";
import { useLanguage } from "@/context/LanguageContext";
import {
  getIncomingInvites,
  respondToInvite,
  type IncomingInvite,
  type InviteResponse,
} from "@/lib/api";
import { useCachedState } from "@/hooks/useCachedState";

export interface IncomingInvitesSectionProps {
  initialInvites?: IncomingInvite[];
  onAnswered?: (title: string, response: InviteResponse) => void;
}

/** Calendar invites sent straight to the owner by a known contact or about one of our properties. */
export function IncomingInvitesSection({ initialInvites, onAnswered }: IncomingInvitesSectionProps) {
  const { t } = useLanguage();
  const [invites, setInvites] = useCachedState<IncomingInvite[]>("today.invites", initialInvites ?? []);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // An RSVP answers the invite as it is now: locked until this visit has fetched it.
  const [fresh, setFresh] = useState(Boolean(initialInvites));

  useEffect(() => {
    if (initialInvites) return;
    let mounted = true;
    getIncomingInvites().then((list) => {
      if (!mounted) return;
      setInvites(list);
      setFresh(true);
    });
    return () => {
      mounted = false;
      setFresh(false);
    };
  }, [initialInvites, setInvites]);

  if (invites.length === 0) return null;

  const answer = async (invite: IncomingInvite, response: InviteResponse) => {
    setBusyId(invite.id);
    setError(null);
    const res = await respondToInvite(invite.id, response);
    setBusyId(null);
    if (!res.ok) {
      setError(res.error ?? t("Could not update the invite"));
      return;
    }
    setInvites((prev) => prev.filter((i) => i.id !== invite.id));
    onAnswered?.(invite.title, response);
  };

  return (
    <div data-testid="incoming-invites" className="border-b border-[var(--line)] bg-amber-500/5">
      <div className="px-4 sm:px-5 pt-3 pb-1 font-mono text-[11px] font-semibold uppercase tracking-wide text-[var(--ink-3)]">
        {t("Incoming Invites")} ({invites.length})
      </div>
      {error && <p className="px-4 sm:px-5 text-xs text-red-600 dark:text-red-400">{error}</p>}
      <ul className="divide-y divide-[var(--line)]">
        {invites.map((invite) => {
          const start = new Date(invite.startTime);
          const end = new Date(invite.endTime);
          const who = invite.person
            ? `${invite.person.name}${invite.person.trade ? ` · ${invite.person.trade}` : ` · ${invite.person.kind}`}`
            : invite.organizerName || invite.organizerEmail;
          const busy = busyId === invite.id || !fresh;
          return (
            <li key={invite.id} className="px-4 sm:px-5 py-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-[13.5px] font-semibold text-[var(--ink)]">{invite.title}</h4>
                <span className="font-mono text-xs tabular-nums text-[var(--ink-2)] inline-flex items-center gap-1.5">
                  <Calendar className="w-3.5 h-3.5 stroke-[1.5]" />
                  {formatDate(start)} · {formatClock(start)} – {formatClock(end)}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--ink-2)]">
                <span>
                  <span className="text-[var(--ink-3)]">{t("From")}:</span> {who}{" "}
                  <span className="font-mono text-[11px] text-[var(--ink-3)]">&lt;{invite.organizerEmail}&gt;</span>
                </span>
                {invite.matchedBy === "address" && (
                  <span className="font-mono text-[10.5px] text-amber-700 dark:text-amber-400">
                    {t("Unknown sender: matched by address only")}
                  </span>
                )}
                {(invite.location || invite.unit) && (
                  <span className="inline-flex items-center gap-1">
                    <MapPin className="w-3.5 h-3.5 text-[var(--ink-3)] stroke-[1.5]" />
                    {invite.unit?.label ?? invite.location}
                  </span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => answer(invite, "accepted")}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer",
                    "bg-[var(--ink)] text-white disabled:opacity-50"
                  )}
                >
                  {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  {t("Accept")}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => answer(invite, "declined")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold cursor-pointer border border-[var(--line)] text-[var(--ink)] disabled:opacity-50"
                >
                  <X className="w-3.5 h-3.5" />
                  {t("Decline")}
                </button>
                {invite.htmlLink?.startsWith("https://www.google.com/calendar/") || invite.htmlLink?.startsWith("https://calendar.google.com/") ? (
                  <a
                    href={invite.htmlLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={t("Opens Google Calendar, where you can propose a new time")}
                    className="inline-flex items-center gap-1 text-xs text-[var(--accent-ink)] hover:underline font-medium"
                  >
                    {t("Reschedule")}
                    <ExternalLink className="w-3 h-3 stroke-[1.5]" />
                  </a>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
