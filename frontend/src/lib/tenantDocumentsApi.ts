import { apiFetch, backendUrl } from "@/lib/backend";

/** One BRIXX document of a tenant (their own, their contract's, their unit's or their building's). */
export interface TenantDocument {
  id: string;
  title: string;
  fileName: string;
  category: string;
  source: "Tenant" | "Contract" | "Unit" | "Building" | string;
  sizeBytes: number | null;
  addedOn: string | null;
  available: boolean;
  url: string | null;
}

export type TenantDocumentsResult =
  | { ok: true; documents: TenantDocument[]; total: number; available: number }
  | { ok: false; status: number };

/** GET /api/tenants/{id}/documents: what BRIXX holds for the tenant and which files are already downloaded. */
export async function getTenantDocuments(tenantId: string): Promise<TenantDocumentsResult> {
  try {
    const res = await apiFetch(backendUrl(`/api/tenants/${encodeURIComponent(tenantId)}/documents`), {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return { ok: false, status: res.status };
    const data = await res.json();
    const documents: TenantDocument[] = Array.isArray(data.documents) ? data.documents : [];
    return { ok: true, documents, total: data.total ?? documents.length, available: data.available ?? 0 };
  } catch {
    return { ok: false, status: 0 };
  }
}

/** Where to open a downloaded file (same-origin session cookie). */
export function tenantDocumentFileUrl(doc: TenantDocument): string | null {
  return doc.url ? backendUrl(doc.url) : null;
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
