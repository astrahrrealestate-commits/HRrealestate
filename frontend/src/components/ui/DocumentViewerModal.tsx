"use client";

import React, { useEffect } from "react";
import { X, Download, FileText, ExternalLink, Calendar, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";

export interface DocumentItem {
  id: string;
  title: string;
  category: "lease" | "inspection" | "id" | "compliance" | "invoice";
  date: string;
  size: string;
  pages?: number;
  previewUrl?: string;
  summary?: string;
}

interface DocumentViewerModalProps {
  document: DocumentItem | null;
  onClose: () => void;
  entityName?: string;
  unitLabel?: string;
}

/**
 * Implements Section 5.6.1:
 * - Desktop: 640px dialog with Close and Download
 * - Mobile (< 768px): Full-screen viewer with Close and Download
 */
export function DocumentViewerModal({
  document,
  onClose,
  entityName,
  unitLabel,
}: DocumentViewerModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (document) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [document, onClose]);

  if (!document) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs md:p-4">
      <div className="w-full h-full md:h-auto md:max-h-[90vh] md:max-w-[640px] md:rounded-[var(--radius-pane)] bg-[var(--pane)] border-0 md:border border-[var(--line)] flex flex-col shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">

        {/* Header */}
        <div className="h-14 px-4 sm:px-5 border-b border-[var(--line)] flex items-center justify-between shrink-0 bg-[var(--pane)]">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-md bg-[var(--selected)] flex items-center justify-center shrink-0">
              <FileText className="w-4 h-4 text-[var(--ink-2)]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[var(--ink)] truncate">
                {document.title}
              </h3>
              <p className="text-[11px] text-[var(--ink-3)] truncate">
                {document.date} · {document.size} {document.pages ? `· ${document.pages} pages` : ""}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                alert(`Downloaded: ${document.title}`);
              }}
              className="text-xs border border-[var(--line)] gap-1.5"
            >
              <Download className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Download</span>
            </Button>
            <button
              onClick={onClose}
              className="p-1.5 text-[var(--ink-3)] hover:text-[var(--ink)] rounded-md hover:bg-[var(--selected)] transition-colors cursor-pointer"
              aria-label="Close document preview"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Document Body / Mock Document Content */}
        <div className="flex-1 overflow-y-auto p-5 sm:p-6 space-y-5 bg-[var(--bg)] text-[var(--ink)]">

          {/* Metadata Card */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-lg p-4 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-[var(--ink-3)]">Associated Unit:</span>
              <span className="font-medium text-[var(--ink)]">{unitLabel || "—"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--ink-3)]">Signatory / Party:</span>
              <span className="font-medium text-[var(--ink)]">{entityName || "Harjot Singh · EstateOS"}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--ink-3)]">Verification Hash:</span>
              <span className="font-mono text-[10px] text-[var(--ink-3)]">sha256-8f2a99d0e12</span>
            </div>
          </div>

          {/* Document Content Sheet Simulation */}
          <div className="bg-[var(--pane)] border border-[var(--line)] rounded-lg p-6 sm:p-8 shadow-xs space-y-4">
            <div className="border-b border-[var(--line)] pb-3 flex items-center justify-between">
              <div>
                <span className="text-xs font-mono uppercase tracking-wider text-[var(--ink-3)] block">
                  Official Record · EstateOS Cloud Archival
                </span>
                <h4 className="text-[16px] font-bold text-[var(--ink)] mt-0.5">
                  {document.title}
                </h4>
              </div>
              <div className="flex items-center gap-1 text-[11px] font-medium text-emerald-600 bg-emerald-500/10 px-2 py-0.5 rounded">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Verified</span>
              </div>
            </div>

            <div className="text-xs text-[var(--ink-2)] leading-relaxed space-y-3 font-serif">
              <p>
                {document.summary ||
                  `This certified residential tenancy instrument is executed in accordance with Dutch civil code (Burgerlijk Wetboek Boek 7, Titel 4). All terms, indexing parameters (CPI + 1.0%), and deposit covenants have been validated and filed in the municipal registry.`}
              </p>
              <p>
                Key Covenants:
                <br />
                1. Monthly rent payable strictly on the 1st of each calendar month.
                <br />
                2. Mandatory annual maintenance review for mechanical ventilation and gas systems.
                <br />
                3. Subletting without prior written consent from EstateOS property administration is prohibited.
              </p>
            </div>

            <div className="pt-4 border-t border-[var(--line)]/60 flex items-center justify-between text-[11px] text-[var(--ink-3)]">
              <span>Digitally signed via iDIN / DigiD</span>
              <span className="font-mono">{document.date}</span>
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="p-3 border-t border-[var(--line)] bg-[var(--pane)] flex items-center justify-end shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-xs border border-[var(--line)]"
          >
            Close preview
          </Button>
        </div>

      </div>
    </div>
  );
}
