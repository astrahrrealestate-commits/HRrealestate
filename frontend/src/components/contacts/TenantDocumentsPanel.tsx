"use client";

import React, { useEffect, useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import {
  formatBytes,
  getTenantDocuments,
  tenantDocumentFileUrl,
  type TenantDocument,
  type TenantDocumentsResult,
} from "@/lib/tenantDocumentsApi";

const SOURCE_ORDER = ["Tenant", "Contract", "Unit", "Building"];
const SOURCE_HELP: Record<string, string> = {
  Tenant: "Attached to the tenant in BRIXX",
  Contract: "Attached to the tenancy contract",
  Unit: "Attached to the unit",
  Building: "Attached to the building",
};

function Row({ doc }: { doc: TenantDocument }) {
  const url = tenantDocumentFileUrl(doc);
  const meta = [doc.category, doc.addedOn, formatBytes(doc.sizeBytes)].filter(Boolean).join(" · ");
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="flex items-start gap-2.5 min-w-0">
        <FileText className="w-4 h-4 mt-0.5 text-[#64748b] shrink-0" />
        <div className="min-w-0">
          <p className="text-[13px] font-medium text-[#111215] truncate">{doc.title}</p>
          <p className="text-[11px] text-[#64748b] truncate">{meta}</p>
        </div>
      </div>
      {url ? (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 inline-flex items-center gap-1 h-[28px] px-3 text-[11.5px] font-medium rounded-full border border-[#e5e7eb] text-[#0f172a] hover:bg-[#f8fafc]"
        >
          <Download className="w-3.5 h-3.5" />
          Open
        </a>
      ) : (
        <span className="shrink-0 inline-flex items-center gap-1 text-[11px] text-[#94a3b8]">
          <Loader2 className="w-3 h-3 animate-spin" /> Fetching from BRIXX...
        </span>
      )}
    </li>
  );
}

/** The tenant's BRIXX documents, grouped by what they are attached to. */
export function TenantDocumentsPanel({ tenantId, name }: { tenantId: string; name: string }) {
  // The answer is kept with the tenant it belongs to, so switching tenant shows "loading" without a reset in the effect.
  const [loaded, setLoaded] = useState<{ tenantId: string; result: TenantDocumentsResult } | null>(null);

  useEffect(() => {
    let current = true;
    getTenantDocuments(tenantId).then((r) => {
      if (current) setLoaded({ tenantId, result: r });
    });
    return () => {
      current = false;
    };
  }, [tenantId]);

  const result = loaded?.tenantId === tenantId ? loaded.result : null;
  const waiting = result?.ok ? result.total - result.available : 0;

  // Files are downloaded from BRIXX in the background: while some are still on their way, look again (for 10 minutes).
  useEffect(() => {
    if (waiting === 0) return;
    let current = true;
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (Date.now() - started > 10 * 60 * 1000) return window.clearInterval(timer);
      getTenantDocuments(tenantId).then((r) => {
        if (current && r.ok) setLoaded({ tenantId, result: r });
      });
    }, 15000);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [tenantId, waiting]);

  return (
    <div className="flex-1 flex flex-col p-3.5 sm:p-6 space-y-4 bg-white" data-testid="tenant-documents">
      <div>
        <h3 className="text-sm font-semibold text-[#111215]">Documents</h3>
        <p className="text-xs text-[#64748b] mt-0.5">
          {result?.ok
            ? `${result.total} in BRIXX for ${name}, ${result.available} ready to open${
                result.total > result.available ? " (the rest are being fetched and appear here by themselves)" : ""
              }`
            : `Files BRIXX holds for ${name}`}
        </p>
      </div>
      {result === null ? (
        <div className="flex items-center gap-2 text-xs text-[#64748b] py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading documents...
        </div>
      ) : !result.ok ? (
        <div className="text-center py-12 text-xs text-[#b91c1c] border border-dashed border-[#fecaca] rounded-xl">
          Documents could not be loaded{result.status === 403 ? ": you do not have access to tenant documents" : ""}.
        </div>
      ) : result.documents.length === 0 ? (
        <div className="text-center py-12 text-[#94a3b8] text-xs border border-dashed border-[#e2e8f0] rounded-xl">
          BRIXX has no documents for this tenant.
        </div>
      ) : (
        SOURCE_ORDER.map((source) => {
          const docs = result.documents.filter((d) => d.source === source);
          if (docs.length === 0) return null;
          return (
            <section key={source}>
              <h4 className="text-[11px] font-bold uppercase tracking-wide text-[#64748b]">
                {source} <span className="font-normal normal-case">· {SOURCE_HELP[source]}</span>
              </h4>
              <ul className="divide-y divide-[#f1f5f9]">
                {docs.map((doc) => (
                  <Row key={`${source}-${doc.id}`} doc={doc} />
                ))}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
