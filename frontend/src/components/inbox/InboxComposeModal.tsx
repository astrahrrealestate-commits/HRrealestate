"use client";

import React, { useState, useEffect } from "react";
import { X, Mail, MessageSquare, ExternalLink, Loader2, Languages } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { createGmailDraft, getContactsList, translateText } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ComposeContact {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  unit?: string;
}

interface InboxComposeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onToast?: (msg: string) => void;
}

export function InboxComposeModal({ isOpen, onClose, onToast }: InboxComposeModalProps) {
  const [channel, setChannel] = useState<"gmail" | "whatsapp">("gmail");
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [contacts, setContacts] = useState<ComposeContact[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [isTranslating, setIsTranslating] = useState(false);

  useEffect(() => {
    if (!isOpen) return;
    getContactsList("all")
      .then((list) => {
        if (Array.isArray(list)) {
          setContacts(
            list.slice(0, 40).map((c: any) => ({
              id: String(c.id ?? c.name ?? ""),
              name: String(c.name ?? ""),
              email: c.email || undefined,
              phone: c.phone || undefined,
              unit: c.unit || undefined,
            }))
          );
        }
      })
      .catch(() => {});
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleTranslateDutch = async () => {
    if (!body.trim() || isTranslating) return;
    setIsTranslating(true);
    try {
      const res = await translateText(body.trim(), "nl");
      if (res?.text) setBody(res.text);
    } finally {
      setIsTranslating(false);
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!to.trim() || !body.trim()) return;
    setIsSending(true);
    try {
      if (channel === "gmail") {
        const res = await createGmailDraft({
          to_email: to.trim(),
          subject: subject.trim() || "Message from HR Real Estate",
          body: body.trim(),
        });
        window.open(res.web_url, "_blank", "noopener,noreferrer");
        onToast?.("Opened Gmail compose window.");
      } else {
        const digits = to.replace(/[^0-9]/g, "");
        window.open(
          `https://wa.me/${digits}?text=${encodeURIComponent(body.trim())}`,
          "_blank",
          "noopener,noreferrer"
        );
        onToast?.("Opened WhatsApp chat.");
      }
      setTo("");
      setSubject("");
      setBody("");
      onClose();
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="fixed inset-0 bg-black/35 backdrop-blur-[1px]" onClick={onClose} />
      <form
        onSubmit={handleSend}
        className="relative z-10 w-full sm:max-w-lg bg-[var(--pane)] border border-[var(--line)] rounded-t-[16px] sm:rounded-[14px] shadow-2xl flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150"
      >
        <div className="px-4 py-3 border-b border-[var(--line)] bg-[var(--bg)]/60 flex items-center justify-between">
          <span className="font-heading font-bold text-[15px] text-[var(--ink)]">
            New Message
          </span>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-[7px] border border-[var(--line)] bg-[var(--pane)] p-0.5 text-[11.5px]">
              <button
                type="button"
                onClick={() => setChannel("gmail")}
                className={cn(
                  "px-2.5 py-1 rounded-[5px] inline-flex items-center gap-1.5 cursor-pointer transition-colors",
                  channel === "gmail"
                    ? "bg-[#0A1B2F] text-white font-semibold"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                )}
              >
                <Mail className="w-3 h-3" />
                <span>Gmail</span>
              </button>
              <button
                type="button"
                onClick={() => setChannel("whatsapp")}
                className={cn(
                  "px-2.5 py-1 rounded-[5px] inline-flex items-center gap-1.5 cursor-pointer transition-colors",
                  channel === "whatsapp"
                    ? "bg-[#0A1B2F] text-white font-semibold"
                    : "text-[var(--ink-2)] hover:text-[var(--ink)]"
                )}
              >
                <MessageSquare className="w-3 h-3" />
                <span>WhatsApp</span>
              </button>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1 rounded-md text-[var(--ink-3)] hover:text-[var(--ink)] hover:bg-[var(--selected)] cursor-pointer"
              aria-label="Close compose"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="p-4 space-y-3 text-[13px]">
          <div className="space-y-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
              {channel === "gmail" ? "To (Email)" : "To (Phone)"}
            </label>
            <input
              type="text"
              list="inbox-compose-contacts"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              placeholder={channel === "gmail" ? "tenant@example.nl" : "+31 6 12 34 56 78"}
              required
              className="w-full h-9 px-3 rounded-[var(--radius-ctl)] bg-[var(--bg)] border border-[var(--line)] text-[var(--ink)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)]"
            />
            <datalist id="inbox-compose-contacts">
              {contacts.map((c) => {
                const val = channel === "gmail" ? c.email : c.phone;
                if (!val) return null;
                return (
                  <option key={c.id} value={val}>
                    {c.name} {c.unit ? `· ${c.unit}` : ""}
                  </option>
                );
              })}
            </datalist>
          </div>

          {channel === "gmail" && (
            <div className="space-y-1">
              <label className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
                Subject
              </label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Regarding your property..."
                className="w-full h-9 px-3 rounded-[var(--radius-ctl)] bg-[var(--bg)] border border-[var(--line)] text-[var(--ink)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)]"
              />
            </div>
          )}

          <div className="space-y-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ink-3)]">
              Message
            </label>
            <textarea
              rows={5}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Write your message..."
              required
              className="w-full p-3 rounded-[var(--radius-ctl)] bg-[var(--bg)] border border-[var(--line)] text-[var(--ink)] focus:outline-none focus:bg-[var(--pane)] focus:border-[var(--ink)] resize-y leading-relaxed"
            />
          </div>
        </div>

        <div className="px-4 py-3 border-t border-[var(--line)] bg-[var(--bg)]/40 flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={() => void handleTranslateDutch()}
            disabled={!body.trim() || isTranslating}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-[var(--line)] bg-[var(--pane)] hover:bg-[var(--selected)] text-[11.5px] font-semibold text-[var(--ink-2)] cursor-pointer disabled:opacity-50"
          >
            {isTranslating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Languages className="w-3 h-3" />}
            <span>Translate to Dutch</span>
          </button>

          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!to.trim() || !body.trim() || isSending}
              icon={<ExternalLink className="w-3.5 h-3.5" />}
            >
              {channel === "gmail" ? "Open in Gmail" : "Open in WhatsApp"}
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
