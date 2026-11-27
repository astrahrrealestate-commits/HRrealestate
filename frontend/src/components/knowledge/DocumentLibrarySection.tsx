"use client";

import React, { useEffect, useState } from "react";
import { BookMarked, ExternalLink, FileText, Loader2, Search } from "lucide-react";
import {
  listDocuments,
  setDocumentReference,
  type DocumentLibraryItem,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Filed document library list with the M13 T6/T12 "Add to reference library" (`is_reference`) toggle.
 */
export function DocumentLibrarySection() {
  const [query, setQuery] = useState("");
  const [refOnly, setRefOnly] = useState(true);
  const [items, setItems] = useState<DocumentLibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listDocuments({ q: query, referenceOnly: refOnly }).then((res) => {
      if (!active) return;
      setItems(res.items);
      setOffline(!res.ok);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [query, refOnly]);

  const toggleReference = async (doc: DocumentLibraryItem) => {
    const next = !doc.is_reference;
    setSavingId(doc.id);
    setError(null);
    const res = await setDocumentReference(doc.id, next);
    setSavingId(null);
    if (!res.ok) {
      setError(res.error || "Could not update reference library status.");
      return;
    }
    setItems((prev) =>
      prev
        .map((item) => (item.id === doc.id ? { ...item, is_reference: next } : item))
        .filter((item) => (!refOnly ? true : item.is_reference))
    );
  };

  return (
    <section className="bg-[var(--pane)] border border-[var(--line)] rounded-[var(--radius-pane)] shadow-2xs overflow-hidden">
      <div className="p-4 sm:p-5 border-b border-[var(--line)] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-sm sm:text-base font-semibold text-[var(--ink)] flex items-center gap-2">
            <BookMarked className="w-4 h-4 text-[var(--accent)]" />
            <span>Documents &amp; Reference Library</span>
          </h2>
          <p className="text-xs text-[var(--ink-2)] mt-1">
            Mark standard terms, ROZ clauses, or templates as reference documents so Astra and Draft Proposer can reuse them safely.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-[var(--ink-3)] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search documents..."
              className="pl-8 pr-3 py-1.5 text-xs rounded-lg border border-[var(--line)] bg-[var(--bg)] text-[var(--ink)] focus:outline-none focus:border-[var(--ink)]"
            />
          </div>
          <button
            type="button"
            onClick={() => setRefOnly((v) => !v)}
            className={cn(
              "px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-colors cursor-pointer whitespace-nowrap",
              refOnly
                ? "bg-[var(--ink)] text-white border-[var(--ink)]"
                : "bg-[var(--bg)] text-[var(--ink-2)] border-[var(--line)] hover:text-[var(--ink)]"
            )}
          >
            Reference only
          </button>
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-red-600 bg-red-500/10 border-b border-red-500/20">
          {error}
        </div>
      )}

      <div className="divide-y divide-[var(--line)]">
        {loading ? (
          <div className="py-10 flex items-center justify-center gap-2 text-xs text-[var(--ink-3)]">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Loading documents…</span>
          </div>
        ) : offline ? (
          <div className="py-10 px-4 text-center text-xs text-[var(--ink-3)]">
            Document library offline. Connect to load filed documents.
          </div>
        ) : items.length === 0 ? (
          <div className="py-10 px-4 text-center text-xs text-[var(--ink-3)]">
            {refOnly ? "No documents marked in the reference library yet." : "No matching documents found."}
          </div>
        ) : (
          items.map((doc) => (
            <div key={doc.id} className="p-4 sm:px-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-2.5 min-w-0">
                <FileText className="w-4 h-4 text-[var(--ink-3)] shrink-0 mt-0.5" />
                <div className="min-w-0 space-y-0.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[13px] font-semibold text-[var(--ink)] truncate">{doc.title}</span>
                    <span className="text-[10.5px] uppercase tracking-wider px-1.5 py-0.5 rounded border border-[var(--line)] bg-[var(--bg)] text-[var(--ink-3)]">
                      {doc.doc_type}
                    </span>
                    {doc.document_date && (
                      <span className="text-[11px] text-[var(--ink-3)]">{doc.document_date}</span>
                    )}
                  </div>
                  {doc.summary && (
                    <p className="text-xs text-[var(--ink-2)] line-clamp-2">{doc.summary}</p>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0 pl-6 sm:pl-0">
                {doc.drive_url && (
                  <a
                    href={doc.drive_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-[var(--line)] text-xs font-medium text-[var(--ink-2)] hover:text-[var(--ink)] hover:bg-[var(--selected)]"
                  >
                    <ExternalLink className="w-3 h-3" />
                    <span>Drive</span>
                  </a>
                )}
                <button
                  type="button"
                  disabled={savingId === doc.id}
                  onClick={() => void toggleReference(doc)}
                  aria-pressed={doc.is_reference}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-3 py-1 rounded-lg border text-xs font-semibold transition-colors cursor-pointer whitespace-nowrap disabled:opacity-60",
                    doc.is_reference
                      ? "bg-emerald-500/15 border-emerald-500/35 text-emerald-700"
                      : "bg-[var(--bg)] border-[var(--line)] text-[var(--ink)] hover:bg-[var(--selected)]"
                  )}
                >
                  {savingId === doc.id && <Loader2 className="w-3 h-3 animate-spin" />}
                  <span>{doc.is_reference ? "In reference library" : "Add to reference library"}</span>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
