"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Check, Lock, Mail, ShieldCheck, UserPlus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  Profile,
  ProfileDraft,
  ProfileRole,
  SectionInfo,
  createProfile,
  updateProfile,
} from "@/lib/adminApi";

interface ProfileBuilderProps {
  isOpen: boolean;
  /** The catalogue of sections to switch on or off, in sidebar order. */
  sections: SectionInfo[];
  /** The profile being edited, or null to create a new one. */
  profile: Profile | null;
  onClose: () => void;
  onSaved: (profile: Profile) => void;
}

const EMPTY: ProfileDraft = { name: "", email: "", role: "member", sections: [] };

/**
 * Create or edit a profile. Left: one switch per dashboard section (what this person will see). Right: who they
 * are. A superadmin always sees every section, so the switches are shown on and locked.
 */
export function ProfileBuilder(props: ProfileBuilderProps) {
  if (!props.isOpen) return null;
  // Keyed so each open starts from the profile's own values without an effect copying them in.
  return <ProfileForm key={props.profile?.id ?? "new"} {...props} />;
}

function startingDraft(profile: Profile | null): ProfileDraft {
  if (!profile) return EMPTY;
  return {
    name: profile.name,
    email: profile.email,
    role: profile.role === "member" || profile.role === "manager" ? "member" : "superadmin",
    sections: profile.sections,
  };
}

function ProfileForm({ sections, profile, onClose, onSaved }: ProfileBuilderProps) {
  const [draft, setDraft] = useState<ProfileDraft>(() => startingDraft(profile));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editing = profile !== null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saving, onClose]);

  const isSuperadmin = draft.role === "superadmin";
  const granted = useMemo(() => new Set(isSuperadmin ? sections.map((s) => s.key) : draft.sections), [
    draft.sections,
    isSuperadmin,
    sections,
  ]);

  const toggle = (key: string) =>
    setDraft((d) => ({
      ...d,
      sections: d.sections.includes(key) ? d.sections.filter((k) => k !== key) : [...d.sections, key],
    }));
  const setAll = (on: boolean) => setDraft((d) => ({ ...d, sections: on ? sections.map((s) => s.key) : [] }));

  const canSave =
    draft.name.trim() !== "" && draft.email.includes("@") && (isSuperadmin || draft.sections.length > 0) && !saving;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    const body = { name: draft.name.trim(), role: draft.role, sections: isSuperadmin ? [] : draft.sections };
    const result = profile
      ? await updateProfile(profile.id, body)
      : await createProfile({ ...body, email: draft.email.trim() });
    setSaving(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved(result.data);
    onClose();
  };

  const field =
    "w-full px-3 py-2 text-[13px] rounded-md border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)] placeholder:text-[var(--ink-3)] focus:outline-none focus:border-[var(--ink)] disabled:opacity-60";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs md:p-4">
      <form
        onSubmit={submit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="profile-builder-title"
        className="w-full h-full md:h-auto md:max-h-[90dvh] md:max-w-[820px] md:rounded-[var(--radius-pane)] bg-[var(--pane)] md:border border-[var(--line)] flex flex-col shadow-2xl overflow-hidden"
      >
        <div className="h-14 px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <UserPlus className="w-4 h-4 text-[var(--ink-2)]" />
            <h2 id="profile-builder-title" className="text-sm font-bold text-[var(--ink)]">
              {editing ? "Edit profile" : "New profile"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            aria-label="Close"
            className="p-1 rounded text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] md:divide-x divide-[var(--line)]">
          {/* LEFT: what this person can see */}
          <section aria-labelledby="sections-title" className="p-5 space-y-3 order-2 md:order-1 border-t md:border-t-0 border-[var(--line)]">
            <div className="flex items-center justify-between">
              <h3 id="sections-title" className="text-xs font-bold uppercase tracking-wider text-[var(--ink-2)]">
                Sections they can see
              </h3>
              {!isSuperadmin && (
                <div className="flex gap-2 text-[11px] font-semibold">
                  <button type="button" onClick={() => setAll(true)} className="text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer">
                    All
                  </button>
                  <span className="text-[var(--ink-3)]">·</span>
                  <button type="button" onClick={() => setAll(false)} className="text-[var(--ink-2)] hover:text-[var(--ink)] cursor-pointer">
                    None
                  </button>
                </div>
              )}
            </div>
            <ul className="space-y-1.5">
              {sections.map((section) => {
                const on = granted.has(section.key);
                return (
                  <li key={section.key}>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={on}
                      disabled={isSuperadmin}
                      onClick={() => toggle(section.key)}
                      className={cn(
                        "w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg border text-left transition-colors",
                        on ? "border-[var(--ink)]/30 bg-[var(--selected)]" : "border-[var(--line)] bg-[var(--bg)]",
                        isSuperadmin ? "cursor-not-allowed opacity-80" : "cursor-pointer hover:bg-[var(--selected)]"
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block text-[13px] font-semibold text-[var(--ink)]">{section.label}</span>
                        <span className="block text-[11.5px] text-[var(--ink-3)] leading-snug">{section.description}</span>
                      </span>
                      <span
                        aria-hidden
                        className={cn(
                          "relative shrink-0 w-9 h-5 rounded-full transition-colors",
                          on ? "bg-emerald-500" : "bg-zinc-300"
                        )}
                      >
                        <span
                          className={cn(
                            "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                            on && "translate-x-4"
                          )}
                        />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {isSuperadmin ? (
              <p className="flex items-center gap-1.5 text-[11.5px] text-[var(--ink-3)]">
                <Lock className="w-3 h-3" /> A superadmin sees every section and manages the team.
              </p>
            ) : (
              <p className="text-[11.5px] text-[var(--ink-3)]">
                {draft.sections.length === 0
                  ? "Switch on at least one section."
                  : `${draft.sections.length} of ${sections.length} sections on.`}
              </p>
            )}
          </section>

          {/* RIGHT: who they are */}
          <section className="p-5 space-y-4 order-1 md:order-2">
            <div className="space-y-1.5">
              <label htmlFor="profile-name" className="text-xs font-semibold text-[var(--ink)]">
                Profile name
              </label>
              <input
                id="profile-name"
                autoFocus
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                maxLength={200}
                placeholder="e.g. Maintenance coordinator"
                className={field}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="profile-email" className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" /> Google account
              </label>
              <input
                id="profile-email"
                type="email"
                value={draft.email}
                onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                disabled={editing}
                maxLength={320}
                placeholder="name@company.com"
                className={field}
                required
              />
              <p className="text-[11.5px] text-[var(--ink-3)]">
                {editing ? "The email cannot change; create a new profile instead." : "They sign in with this Google account."}
              </p>
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-[var(--ink-3)]" /> Role
              </legend>
              <div className="grid grid-cols-2 gap-2">
                {(
                  [
                    ["member", "Member", "Only the sections switched on"],
                    ["superadmin", "Superadmin", "Everything, and manages the team"],
                  ] as [ProfileRole, string, string][]
                ).map(([value, label, hint]) => (
                  <label
                    key={value}
                    className={cn(
                      "flex flex-col gap-0.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors",
                      draft.role === value ? "border-[var(--ink)] bg-[var(--selected)]" : "border-[var(--line)] bg-[var(--bg)]"
                    )}
                  >
                    <span className="flex items-center gap-2 text-[13px] font-semibold text-[var(--ink)]">
                      <input
                        type="radio"
                        name="profile-role"
                        value={value}
                        checked={draft.role === value}
                        onChange={() => setDraft((d) => ({ ...d, role: value }))}
                        className="accent-black"
                      />
                      {label}
                    </span>
                    <span className="text-[11.5px] text-[var(--ink-3)] leading-snug pl-5">{hint}</span>
                  </label>
                ))}
              </div>
            </fieldset>

            {error && (
              <p role="alert" className="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
                {error}
              </p>
            )}
          </section>
        </div>

        <div className="px-5 py-3 border-t border-[var(--line)] flex items-center justify-end gap-2 shrink-0 bg-[var(--pane)] pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={saving} className="text-xs border border-[var(--line)]">
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={!canSave} className="text-xs gap-1.5">
            <Check className="w-3.5 h-3.5" />
            {saving ? "Saving…" : editing ? "Save changes" : "Create profile"}
          </Button>
        </div>
      </form>
    </div>
  );
}
