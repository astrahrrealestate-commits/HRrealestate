"use client";

import React, { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import { Search, ShieldCheck, UserPlus } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/context/AuthContext";
import { ProfileBuilder } from "@/components/admin/ProfileBuilder";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import { Profile, SectionInfo, listProfiles, listSections, updateProfile } from "@/lib/adminApi";

const roleLabel = (role: string) => (role === "member" || role === "manager" ? "Member" : "Superadmin");

function AdminContent() {
  const { user } = useAuth();
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [sections, setSections] = useState<SectionInfo[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const router = useRouter();
  const wantsNew = useSearchParams().get("new") === "1";
  const [builder, setBuilder] = useState<{ open: boolean; profile: Profile | null }>({ open: wantsNew, profile: null });

  // "Add a profile" in the user menu lands here with ?new=1: the builder is already open, and the flag is dropped
  // so a refresh does not reopen it.
  useEffect(() => {
    if (wantsNew) router.replace("/admin");
  }, [wantsNew, router]);

  const load = useCallback(async () => {
    setLoadError(null);
    const [p, s] = await Promise.all([listProfiles(), listSections()]);
    if (!p.ok) return setLoadError(p.error);
    if (!s.ok) return setLoadError(s.error);
    setProfiles(p.data);
    setSections(s.data);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-mount: load() only sets state after awaiting
    void load();
  }, [load]);

  const labelOf = useMemo(() => new Map(sections.map((s) => [s.key, s.label])), [sections]);
  const visible = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!profiles) return [];
    if (!q) return profiles;
    return profiles.filter((p) => `${p.name} ${p.email} ${roleLabel(p.role)}`.toLowerCase().includes(q));
  }, [profiles, searchQuery]);

  const saved = (profile: Profile) =>
    setProfiles((prev) => {
      if (!prev) return [profile];
      return prev.some((p) => p.id === profile.id) ? prev.map((p) => (p.id === profile.id ? profile : p)) : [...prev, profile];
    });

  const setActive = async (profile: Profile, active: boolean) => {
    if (!active && !window.confirm(`Switch off ${profile.name}? They are signed out on their next click.`)) return;
    setActionError(null);
    const result = await updateProfile(profile.id, { is_active: active });
    if (result.ok) saved(result.data);
    else setActionError(result.error);
  };

  const activeCount = profiles?.filter((p) => p.is_active).length ?? 0;

  return (
    <div className="h-dvh bg-[#0A1B2F] flex font-sans antialiased text-[var(--ink)] overflow-hidden">
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden bg-[#0A1B2F]">
        <TopCommandBar pageTitle="Team & access" hideSearch={true} />

        <div className="flex-1 flex flex-row overflow-hidden min-h-0 w-full relative">
          <div className="flex-1 m-0 mr-[10px] mb-[10px] bg-white rounded-[14px] border border-[#27272a] shadow-[0_2px_8px_rgba(0,0,0,0.2)] flex flex-col overflow-hidden relative">
            <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 max-w-6xl w-full mx-auto pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-12">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--line)] pb-5">
                <div>
                  <h1 className="font-heading font-bold text-[24px] sm:text-[28px] text-[var(--ink)] tracking-tight">
                    Team & access
                  </h1>
                  <p className="text-xs sm:text-[13px] text-[var(--ink-2)] mt-0.5">
                    {profiles
                      ? `${profiles.length} ${profiles.length === 1 ? "profile" : "profiles"} · ${activeCount} active`
                      : "Choose who can sign in and which sections each person sees."}
                  </p>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setBuilder({ open: true, profile: null })}
                  disabled={!profiles}
                  className="text-xs gap-1.5"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                  <span>New profile</span>
                </Button>
              </div>

              <div className="relative sm:w-72">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--ink-3)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search profiles…"
                  aria-label="Search profiles"
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg)] border border-[var(--line)] rounded-md text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none"
                />
              </div>

              {actionError && (
                <p role="alert" className="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
                  {actionError}
                </p>
              )}

              <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] overflow-hidden shadow-2xs divide-y divide-[var(--line)]">
                {loadError && (
                  <div className="text-center py-14 text-xs space-y-3" role="alert">
                    <p className="text-rose-600">{loadError}</p>
                    <Button variant="secondary" size="sm" onClick={() => void load()} className="text-xs">
                      Try again
                    </Button>
                  </div>
                )}
                {!loadError && !profiles && <div className="text-center py-14 text-[var(--ink-3)] text-xs">Loading profiles…</div>}
                {visible.map((profile) => {
                  const isYou = profile.email.toLowerCase() === user?.email.toLowerCase();
                  const everything = profile.role !== "member" && profile.role !== "manager";
                  return (
                    <div
                      key={profile.id}
                      className={cn(
                        "p-4 sm:px-5 sm:py-4 flex flex-col lg:flex-row lg:items-center justify-between gap-3 hover:bg-[var(--selected)]/30 transition-colors",
                        !profile.is_active && "opacity-60"
                      )}
                    >
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="flex items-center gap-2.5 flex-wrap">
                          <span className="font-semibold text-[15px] text-[var(--ink)]">{profile.name}</span>
                          <span className="text-xs px-2 py-0.5 rounded bg-[var(--selected)] text-[var(--ink-2)] border border-[var(--line)] font-medium inline-flex items-center gap-1">
                            {everything && <ShieldCheck className="w-3 h-3" />}
                            {roleLabel(profile.role)}
                          </span>
                          {isYou && <span className="text-[11px] text-[var(--ink-3)]">You</span>}
                          {!profile.is_active && <span className="text-[11px] text-[var(--ink-3)] font-medium">Switched off</span>}
                        </div>
                        <div className="text-xs text-[var(--ink-3)]">{profile.email}</div>
                        <div className="flex flex-wrap gap-1.5">
                          {everything ? (
                            <span className="text-[11px] px-2 py-0.5 rounded-full border border-[var(--line)] text-[var(--ink-2)]">
                              All sections
                            </span>
                          ) : (
                            profile.sections.map((key) => (
                              <span
                                key={key}
                                className="text-[11px] px-2 py-0.5 rounded-full border border-[var(--line)] text-[var(--ink-2)] bg-[var(--bg)]"
                              >
                                {labelOf.get(key) ?? key}
                              </span>
                            ))
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0 self-end lg:self-center">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setBuilder({ open: true, profile })}
                          className="text-xs border border-[var(--line)]"
                        >
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isYou}
                          title={isYou ? "You cannot switch off your own profile" : undefined}
                          onClick={() => void setActive(profile, !profile.is_active)}
                          className="text-xs border border-[var(--line)]"
                        >
                          {profile.is_active ? "Switch off" : "Switch on"}
                        </Button>
                      </div>
                    </div>
                  );
                })}
                {profiles && visible.length === 0 && (
                  <div className="text-center py-14 text-[var(--ink-3)] text-xs">
                    {profiles.length === 0 ? "No profiles yet. Create the first one." : "No profile matches your search."}
                  </div>
                )}
              </div>

              <p className="text-xs text-[var(--ink-3)] leading-relaxed">
                A change applies on the person&apos;s next click. Sections limit the pages and the data behind them; the
                Super Agent answers from the whole portfolio, so give it only to people you trust with all of it.
              </p>
            </main>
          </div>

          <AskEstateOSPanel currentPageName="Admin" selectedContext="Team & access" />
        </div>
      </div>

      <MobileTabBar />

      <ProfileBuilder
        isOpen={builder.open}
        sections={sections}
        profile={builder.profile}
        onClose={() => setBuilder((b) => ({ ...b, open: false }))}
        onSaved={saved}
      />
    </div>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-[var(--ink-3)]">Loading…</div>}>
      <AdminContent />
    </Suspense>
  );
}
