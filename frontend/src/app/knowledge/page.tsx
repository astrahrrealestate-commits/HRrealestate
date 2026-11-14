"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopCommandBar } from "@/components/layout/TopCommandBar";
import { MobileTabBar } from "@/components/layout/MobileTabBar";
import { Button } from "@/components/ui/Button";
import { AskEstateOSPanel } from "@/components/assistant/AskEstateOSPanel";
import {
  BookOpen,
  FileText,
  FileUp,
  Save,
  RotateCcw,
  Loader2,
  Check,
  AlertCircle,
  Download,
  Eye,
  Code2,
  Sparkles,
  Info,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getOwnerPersona,
  resetOwnerPersona,
  saveOwnerPersona,
  type OwnerPersona,
} from "@/lib/api";

const ACCEPTED_EXTENSIONS = ".md,.markdown,.txt,text/markdown,text/plain";

function SimpleMarkdownPreview({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <div className="text-[var(--ink-3)] italic text-sm py-8 text-center">
        No content to preview.
      </div>
    );
  }

  const lines = content.split("\n");

  return (
    <div className="prose prose-sm max-w-none text-[var(--ink)] space-y-3 leading-relaxed">
      {lines.map((line, idx) => {
        const trimmed = line.trim();

        if (trimmed.startsWith("# ")) {
          return (
            <h1
              key={idx}
              className="text-xl font-heading font-bold text-[var(--ink)] mt-4 mb-2 pb-1 border-b border-[var(--line)]"
            >
              {trimmed.slice(2)}
            </h1>
          );
        }
        if (trimmed.startsWith("## ")) {
          return (
            <h2
              key={idx}
              className="text-base font-heading font-semibold text-[var(--ink)] mt-4 mb-1.5"
            >
              {trimmed.slice(3)}
            </h2>
          );
        }
        if (trimmed.startsWith("### ")) {
          return (
            <h3
              key={idx}
              className="text-sm font-heading font-semibold text-[var(--ink-2)] mt-3 mb-1"
            >
              {trimmed.slice(4)}
            </h3>
          );
        }
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          const bulletContent = trimmed.slice(2);
          // Highlight strong/bold **text**
          const parts = bulletContent.split(/(\*\*[^*]+\*\*)/g);
          return (
            <div key={idx} className="flex items-start gap-2 pl-2 text-[13.5px]">
              <span className="text-[var(--accent)] font-bold mt-1 text-xs">•</span>
              <span className="text-[var(--ink-2)]">
                {parts.map((part, pIdx) =>
                  part.startsWith("**") && part.endsWith("**") ? (
                    <strong key={pIdx} className="font-semibold text-[var(--ink)]">
                      {part.slice(2, -2)}
                    </strong>
                  ) : (
                    part
                  )
                )}
              </span>
            </div>
          );
        }
        if (trimmed === "") {
          return <div key={idx} className="h-2" />;
        }

        // Standard paragraph
        const parts = line.split(/(\*\*[^*]+\*\*)/g);
        return (
          <p key={idx} className="text-[13.5px] text-[var(--ink-2)]">
            {parts.map((part, pIdx) =>
              part.startsWith("**") && part.endsWith("**") ? (
                <strong key={pIdx} className="font-semibold text-[var(--ink)]">
                  {part.slice(2, -2)}
                </strong>
              ) : (
                part
              )
            )}
          </p>
        );
      })}
    </div>
  );
}

function KnowledgeContent() {
  const [persona, setPersona] = useState<OwnerPersona | null>(null);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | undefined>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [activeTab, setActiveTab] = useState<"edit" | "preview">("edit");
  const [isAskAgentOpen, setIsAskAgentOpen] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const applyPersona = (p: OwnerPersona) => {
    setPersona(p);
    setText(p.content);
    setFileName(undefined);
  };

  useEffect(() => {
    getOwnerPersona()
      .then((p) => {
        if (p) {
          applyPersona(p);
        } else {
          setMessage({
            kind: "error",
            text: "Could not load the persona document. Ensure backend services are running.",
          });
        }
      })
      .finally(() => setLoading(false));
  }, []);

  const limit = persona?.max_chars ?? 8000;
  const isDirty =
    persona !== null &&
    (text.trim() !== persona.content.trim() || fileName !== undefined);
  const isTooLong = text.length > limit;

  const handleSave = async () => {
    setBusy(true);
    setMessage(null);
    const baseName = fileName ? fileName.replace(/\.[^.]+$/, "") : undefined;
    const result = await saveOwnerPersona({
      content: text,
      name: baseName,
      filename: fileName,
    });
    if ("persona" in result) {
      applyPersona(result.persona);
      setMessage({
        kind: "ok",
        text: `Changes saved successfully as version v${result.persona.version}. Proposer drafts will immediately use this persona.`,
      });
    } else {
      setMessage({ kind: "error", text: result.error });
    }
    setBusy(false);
  };

  const handleReset = async () => {
    if (
      !window.confirm(
        "Reset persona back to the default sample template? Any unsaved edits will be replaced."
      )
    ) {
      return;
    }
    setBusy(true);
    setMessage(null);
    const p = await resetOwnerPersona();
    if (p) {
      applyPersona(p);
      setMessage({ kind: "ok", text: "Reset successfully to default sample persona." });
    } else {
      setMessage({ kind: "error", text: "Could not reset persona template." });
    }
    setBusy(false);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 100_000) {
      setMessage({
        kind: "error",
        text: "The uploaded file is too large for a persona (maximum 8,000 characters).",
      });
      return;
    }
    const uploadedContent = await file.text();
    setText(uploadedContent);
    setFileName(file.name);
    setActiveTab("edit");
    setMessage({
      kind: "ok",
      text: `Loaded content from ${file.name}. Review below and click "Save Changes" to apply.`,
    });
  };

  const handleDownload = () => {
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName || "persona.md";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-dvh bg-[var(--bg)] text-[var(--ink)] overflow-hidden">
      {/* Desktop Navigation Sidebar */}
      <Sidebar />

      {/* Main View Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden relative">
        <TopCommandBar
          pageTitle="Knowledge Base"
          hideSearch
          onAskAgent={() => setIsAskAgentOpen(true)}
        />

        {/* Scrollable Page Body */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-6 pb-24 md:pb-8">
          <div className="max-w-5xl mx-auto space-y-6">
            {/* Page Header */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[var(--line)]">
              <div>
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-[var(--pane)] border border-[var(--line)] flex items-center justify-center text-[var(--accent)] shadow-2xs">
                    <BookOpen className="w-4 h-4" />
                  </div>
                  <h1 className="text-xl sm:text-2xl font-heading font-bold text-[var(--ink)] tracking-tight">
                    Knowledge Base
                  </h1>
                </div>
                <p className="text-xs sm:text-[13px] text-[var(--ink-2)] mt-1.5">
                  Authoritative operating knowledge, tone profiles, and instructions for EstateOS draft agents.
                </p>
              </div>

              {/* Status Badge */}
              {persona && (
                <div className="flex items-center gap-2 self-start sm:self-auto bg-[var(--pane)] px-3 py-1.5 rounded-full border border-[var(--line)] text-xs text-[var(--ink-2)] shadow-2xs">
                  <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                  <span className="font-medium text-[var(--ink)]">persona.md</span>
                  <span className="text-[var(--ink-3)]">·</span>
                  <span>v{persona.version}</span>
                  {persona.is_default && (
                    <span className="text-[10px] text-amber-500 bg-amber-500/10 px-1.5 py-0.5 rounded font-medium">
                      Sample
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Document Card Shell */}
            <div className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] shadow-2xs overflow-hidden">
              {/* Document Banner */}
              <div className="p-4 sm:p-5 border-b border-[var(--line)] bg-[var(--pane)] flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-[var(--selected)] border border-[var(--line)] flex items-center justify-center text-[var(--accent)] shrink-0 mt-0.5">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm sm:text-base font-semibold text-[var(--ink)]">
                        Harjot Singh — Writing Persona
                      </h2>
                      <span className="text-[11px] font-mono bg-[var(--selected)] text-[var(--ink-2)] px-2 py-0.5 rounded border border-[var(--line)]">
                        persona.md
                      </span>
                    </div>
                    <p className="text-xs text-[var(--ink-2)] mt-1">
                      Governs communication tone, greetings, Dutch vs. English formality, and sign-offs for all tenant and contractor message drafts.
                    </p>
                  </div>
                </div>

                {/* Edit vs Preview View Toggle */}
                <div className="flex items-center bg-[var(--bg)] border border-[var(--line)] rounded-lg p-0.5 shrink-0 self-start md:self-auto">
                  <button
                    type="button"
                    onClick={() => setActiveTab("edit")}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer",
                      activeTab === "edit"
                        ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs"
                        : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                    )}
                  >
                    <Code2 className="w-3.5 h-3.5" />
                    Editor
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab("preview")}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer",
                      activeTab === "preview"
                        ? "bg-[var(--pane)] text-[var(--ink)] shadow-2xs"
                        : "text-[var(--ink-3)] hover:text-[var(--ink)]"
                    )}
                  >
                    <Eye className="w-3.5 h-3.5" />
                    Preview
                  </button>
                </div>
              </div>

              {/* Status / Alert Feedback */}
              {message && (
                <div
                  className={cn(
                    "px-4 py-3 border-b text-xs flex items-center justify-between gap-2 transition-all",
                    message.kind === "ok"
                      ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
                      : "bg-red-500/10 border-red-500/20 text-red-400"
                  )}
                >
                  <div className="flex items-center gap-2">
                    {message.kind === "ok" ? (
                      <Check className="w-4 h-4 shrink-0 text-emerald-400" />
                    ) : (
                      <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
                    )}
                    <span>{message.text}</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setMessage(null)}
                    className="text-xs opacity-75 hover:opacity-100 cursor-pointer"
                  >
                    Dismiss
                  </button>
                </div>
              )}

              {/* Main Content Area */}
              <div className="p-4 sm:p-6">
                {loading ? (
                  <div className="flex flex-col items-center justify-center py-20 text-[var(--ink-3)] space-y-3">
                    <Loader2 className="w-6 h-6 animate-spin text-[var(--accent)]" />
                    <span className="text-xs">Loading persona.md…</span>
                  </div>
                ) : activeTab === "edit" ? (
                  <div className="space-y-3">
                    <textarea
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      spellCheck={false}
                      aria-label="Persona markdown editor"
                      rows={18}
                      className="w-full font-mono text-[13px] leading-relaxed p-4 rounded-xl border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] transition-all resize-y min-h-[380px]"
                      placeholder="# Enter persona markdown here..."
                    />
                    <div className="flex items-center justify-between text-[11px] text-[var(--ink-3)] pt-1 px-1">
                      <span>Standard Markdown supported (`#`, `##`, `- bullets`, `**bold**`)</span>
                      <span className={isTooLong ? "text-red-500 font-semibold" : ""}>
                        {text.length.toLocaleString()} / {limit.toLocaleString()} chars
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="p-6 rounded-xl border border-[var(--line)] bg-[var(--bg)] min-h-[380px] overflow-y-auto">
                    <SimpleMarkdownPreview content={text} />
                  </div>
                )}
              </div>

              {/* Action Toolbar */}
              <div className="p-4 sm:px-6 bg-[var(--pane)] border-t border-[var(--line)] flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  {/* Save Button */}
                  <Button
                    variant="primary"
                    onClick={handleSave}
                    disabled={busy || !isDirty || isTooLong || !text.trim()}
                    className="gap-1.5 shadow-2xs font-medium"
                  >
                    {busy ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5" />
                    )}
                    <span>Save Changes</span>
                  </Button>

                  {/* Upload .md File */}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept={ACCEPTED_EXTENSIONS}
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                  <Button
                    variant="secondary"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={busy}
                    className="gap-1.5 text-xs"
                  >
                    <FileUp className="w-3.5 h-3.5" />
                    <span>Upload .md</span>
                  </Button>

                  {/* Download .md */}
                  <Button
                    variant="secondary"
                    onClick={handleDownload}
                    disabled={busy || !text.trim()}
                    className="gap-1.5 text-xs"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>Download</span>
                  </Button>

                  {/* Reset to Sample */}
                  <Button
                    variant="secondary"
                    onClick={handleReset}
                    disabled={busy || persona?.is_default}
                    className="gap-1.5 text-xs text-[var(--ink-2)]"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    <span>Reset Sample</span>
                  </Button>
                </div>

                {/* Safety / Invariant Notice */}
                <div className="flex items-center gap-1.5 text-[11px] text-[var(--ink-3)]">
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                  <span>Drafts require Harjot's manual approval before sending</span>
                </div>
              </div>
            </div>

            {/* Info Callout Card */}
            <div className="border border-[var(--line)] rounded-[var(--radius-pane)] bg-[var(--pane)] p-4 sm:p-5 flex items-start gap-3.5 text-xs sm:text-[13px] text-[var(--ink-2)]">
              <Info className="w-5 h-5 text-[var(--accent)] shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-semibold text-[var(--ink)]">
                  How this document is used by EstateOS
                </p>
                <p className="leading-relaxed">
                  Whenever tickets arrive from tenants or contractors via WhatsApp or Gmail, the <strong>Proposer Agent</strong> reads this persona file inside a protected sandbox block. It crafts replies mirroring your exact tone, greeting customs, and Dutch/English language choices.
                </p>
              </div>
            </div>
          </div>
        </main>
      </div>

      {/* Mobile Bottom Tab Bar */}
      <MobileTabBar />

      {/* Floating Ask Astra Panel */}
      <AskEstateOSPanel
        isOpen={isAskAgentOpen}
        onClose={() => setIsAskAgentOpen(false)}
      />
    </div>
  );
}

export default function KnowledgePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-dvh items-center justify-center bg-[var(--bg)] text-xs text-[var(--ink-3)]">
          <Loader2 className="w-5 h-5 animate-spin mr-2 text-[var(--accent)]" />
          Loading Knowledge Base…
        </div>
      }
    >
      <KnowledgeContent />
    </Suspense>
  );
}

