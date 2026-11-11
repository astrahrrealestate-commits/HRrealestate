"use client";

import React, { useEffect, useState } from "react";
import { Check, Mail, Phone, UserPlus, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  CONTACT_TYPES,
  ContactDraft,
  ContactType,
  SavedContact,
  addContact,
  classifyContact,
  typeOf,
} from "@/lib/contactsWriteApi";
import type { ContactItem } from "@/data/contactsMockData";

interface ContactFormModalProps {
  isOpen: boolean;
  /** The contact being named or classified, or null to add a new one. */
  contact: ContactItem | null;
  onClose: () => void;
  onSaved: (contact: SavedContact) => void;
}

const EMPTY: ContactDraft = { name: "", type: "contractor", trade: "", email: "", phone: "" };

/** Add a contact by hand, or give a name and a type to someone mail or WhatsApp already brought in. */
export function ContactFormModal(props: ContactFormModalProps) {
  if (!props.isOpen) return null;
  // Keyed so each open starts from the contact's own values without an effect copying them in.
  return <ContactForm key={props.contact?.id ?? "new"} {...props} />;
}

/** The trade as stored (never the display label), so saving does not turn "Contact" into a trade. */
function storedTrade(contact: ContactItem): string {
  const trade = (contact as SavedContact).trade ?? "";
  return trade.toLowerCase() === "other" ? "" : trade;
}

function startingDraft(contact: ContactItem | null): ContactDraft {
  if (!contact) return EMPTY;
  return {
    name: contact.name,
    type: typeOf(contact),
    trade: storedTrade(contact),
    email: contact.email,
    phone: contact.phone,
  };
}

function ContactForm({ contact, onClose, onSaved }: ContactFormModalProps) {
  const [draft, setDraft] = useState<ContactDraft>(() => startingDraft(contact));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const editing = contact !== null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !saving && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saving, onClose]);

  const picked = CONTACT_TYPES.find((t) => t.value === draft.type);
  const canSave = draft.name.trim() !== "" && !saving;
  const pick = (type: ContactType) => setDraft((d) => ({ ...d, type }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    const result = contact ? await classifyContact(contact.id, draft) : await addContact(draft);
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
        aria-labelledby="contact-form-title"
        className="w-full h-full md:h-auto md:max-h-[90dvh] md:max-w-[520px] md:rounded-[var(--radius-pane)] bg-[var(--pane)] md:border border-[var(--line)] flex flex-col shadow-2xl overflow-hidden"
      >
        <div className="h-14 px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5">
            <UserPlus className="w-4 h-4 text-[var(--ink-2)]" />
            <h2 id="contact-form-title" className="text-sm font-bold text-[var(--ink)]">
              {editing ? "Edit contact" : "Add contact"}
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

        <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-4">
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-semibold text-[var(--ink)]">Who are they?</legend>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Contact type">
              {CONTACT_TYPES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={draft.type === t.value}
                  onClick={() => pick(t.value)}
                  className={cn(
                    "px-3 py-1.5 rounded-full border text-[12.5px] font-medium transition-colors cursor-pointer",
                    draft.type === t.value
                      ? "border-[var(--ink)] bg-[var(--ink)] text-white"
                      : "border-[var(--line)] bg-[var(--bg)] text-[var(--ink-2)] hover:bg-[var(--selected)]"
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {picked && <p className="text-[11.5px] text-[var(--ink-3)]">{picked.hint}</p>}
          </fieldset>

          <div className="space-y-1.5">
            <label htmlFor="contact-name" className="text-xs font-semibold text-[var(--ink)]">
              Name
            </label>
            <input
              id="contact-name"
              autoFocus
              value={draft.name}
              onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              maxLength={200}
              placeholder="Full name or company"
              className={field}
              required
            />
          </div>

          {picked?.needsTrade && (
            <div className="space-y-1.5">
              <label htmlFor="contact-trade" className="text-xs font-semibold text-[var(--ink)]">
                {draft.type === "other" ? "Role" : "Trade"} <span className="font-normal text-[var(--ink-3)]">(optional)</span>
              </label>
              <input
                id="contact-trade"
                value={draft.trade}
                onChange={(e) => setDraft((d) => ({ ...d, trade: e.target.value }))}
                maxLength={100}
                placeholder={draft.type === "maintenance" ? "Maintenance" : draft.type === "other" ? "e.g. Notary" : "e.g. Plumber"}
                className={field}
              />
            </div>
          )}

          <div className="grid sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label htmlFor="contact-email" className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-[var(--ink-3)]" /> Email
              </label>
              <input
                id="contact-email"
                type="email"
                value={draft.email}
                onChange={(e) => setDraft((d) => ({ ...d, email: e.target.value }))}
                disabled={editing}
                maxLength={320}
                placeholder="name@company.com"
                className={field}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="contact-phone" className="text-xs font-semibold text-[var(--ink)] flex items-center gap-1.5">
                <Phone className="w-3.5 h-3.5 text-[var(--ink-3)]" /> WhatsApp / phone
              </label>
              <input
                id="contact-phone"
                type="tel"
                value={draft.phone}
                onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))}
                disabled={editing}
                maxLength={40}
                placeholder="06 12345678"
                className={field}
              />
            </div>
          </div>
          <p className="text-[11.5px] text-[var(--ink-3)] leading-snug">
            {editing
              ? "Their email and number come from the messages they sent."
              : "Messages from this email or number are shown under this contact, including ones they already sent."}
          </p>

          {error && (
            <p role="alert" className="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
              {error}
            </p>
          )}
        </div>

        <div className="px-5 py-3 border-t border-[var(--line)] flex items-center justify-end gap-2 shrink-0 bg-[var(--pane)] pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={saving} className="text-xs border border-[var(--line)]">
            Cancel
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={!canSave} className="text-xs gap-1.5">
            <Check className="w-3.5 h-3.5" />
            {saving ? "Saving…" : editing ? "Save" : "Add contact"}
          </Button>
        </div>
      </form>
    </div>
  );
}
