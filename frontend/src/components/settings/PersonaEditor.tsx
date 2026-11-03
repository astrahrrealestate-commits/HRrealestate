"use client";

import React, { useEffect, useRef, useState } from "react";
import { FileUp, Loader2, RotateCcw, Save, UserRound } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { getOwnerPersona, resetOwnerPersona, saveOwnerPersona, OwnerPersona } from "@/lib/api";

const ACCEPTED = ".md,.markdown,.txt,text/markdown,text/plain";

/**
 * Harjot's writing persona (a markdown file). The draft agent writes every tenant/contractor reply in this voice,
 * and each draft card says "Acting as Harjot" with the persona name and version it used.
 */
export function PersonaEditor() {
  const [persona, setPersona] = useState<OwnerPersona | null>(null);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const apply = (p: OwnerPersona) => {
    setPersona(p);
    setText(p.content);
    setFileName(undefined);
  };

  useEffect(() => {
    getOwnerPersona()
      .then((p) => {
        if (p) apply(p);
        else setMessage({ kind: "error", text: "Could not load the persona. Is the backend running?" });
      })
      .finally(() => setLoading(false));
  }, []);

  const limit = persona?.max_chars ?? 8000;
  const dirty = persona !== null && (text.trim() !== persona.content.trim() || fileName !== undefined);
  const tooLong = text.length > limit;

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    const baseName = fileName ? fileName.replace(/\.[^.]+$/, "") : undefined;
    const result = await saveOwnerPersona({ content: text, name: baseName, filename: fileName });
    if ("persona" in result) {
      apply(result.persona);
      setMessage({ kind: "ok", text: `Saved as version ${result.persona.version}. New drafts use it now.` });
    } else {
      setMessage({ kind: "error", text: result.error });
    }
    setBusy(false);
  };

  const handleReset = async () => {
    setBusy(true);
    setMessage(null);
    const p = await resetOwnerPersona();
    if (p) {
      apply(p);
      setMessage({ kind: "ok", text: "Back to the sample persona." });
    } else {
      setMessage({ kind: "error", text: "Could not reset the persona." });
    }
    setBusy(false);
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 100_000) {
      setMessage({ kind: "error", text: "That file is too large for a persona (max 8,000 characters)." });
      return;
    }
    setText(await file.text());
    setFileName(file.name);
    setMessage({ kind: "ok", text: `Loaded ${file.name}. Review it and press Save to use it.` });
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-[var(--ink-3)] p-4">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading persona…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] p-4">
        <UserRound className="w-5 h-5 text-[var(--accent)] mt-0.5 shrink-0" />
        <div className="min-w-0 text-[13px] text-[var(--ink-2)]">
          <p className="font-semibold text-[var(--ink)]">
            Drafts are written acting as Harjot
            {persona && (
              <span className="font-normal text-[var(--ink-3)]">
                {" "}
                · {persona.name} · v{persona.version}
                {persona.is_default ? " · sample persona" : ""}
              </span>
            )}
          </p>
          <p className="mt-1">
            The draft agent follows this file for voice, language, greeting and sign-off. It cannot change the safety
            rules: nothing is sent without your approval.
          </p>
        </div>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
        aria-label="Persona markdown"
        className="w-full min-h-[320px] font-mono text-[13px] leading-relaxed p-4 rounded-[var(--radius-pane)] border border-[var(--line)] bg-[var(--pane)] text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]"
      />

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={handleSave} disabled={busy || !dirty || tooLong || !text.trim()} className="gap-1.5">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Save persona
        </Button>
        <input ref={fileInput} type="file" accept={ACCEPTED} onChange={handleFile} className="hidden" />
        <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy} className="gap-1.5">
          <FileUp className="w-4 h-4" /> Upload .md
        </Button>
        <Button variant="secondary" onClick={handleReset} disabled={busy || persona?.is_default} className="gap-1.5">
          <RotateCcw className="w-4 h-4" /> Use sample
        </Button>
        <span className={`ml-auto text-[11px] ${tooLong ? "text-red-600" : "text-[var(--ink-3)]"}`}>
          {text.length.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>

      {message && (
        <p role="status" className={`text-[13px] ${message.kind === "error" ? "text-red-600" : "text-emerald-700"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
