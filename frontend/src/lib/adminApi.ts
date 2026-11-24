/** Team profiles and the sections each may open (`/api/v1/admin/*`, superadmin only). */

import { apiFetch, BACKEND_BASE_URL } from "@/lib/backend";

export interface SectionInfo {
  key: string;
  label: string;
  description: string;
}

export type ProfileRole = "superadmin" | "member";

export interface Profile {
  id: string;
  name: string;
  email: string;
  /** "owner" and "manager" exist on older whitelist entries; the builder only writes superadmin | member. */
  role: string;
  sections: string[];
  is_active: boolean;
  invited_by: string | null;
  created_at: string;
}

export interface ProfileDraft {
  name: string;
  email: string;
  role: ProfileRole;
  sections: string[];
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

const BASE = `${BACKEND_BASE_URL}/api/v1/admin`;

/** FastAPI sends `detail` as text, or as a list of field problems for a 422. */
function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  if (status === 403) return "Only a superadmin can manage the team.";
  return "Something went wrong. Try again.";
}

async function call<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  try {
    const res = await apiFetch(`${BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", "Content-Type": "application/json", ...init.headers },
      signal: AbortSignal.timeout(10000),
    });
    const body = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: body as T };
    return { ok: false, error: messageFrom(body, res.status) };
  } catch {
    return { ok: false, error: "Could not reach the server. Check your connection and try again." };
  }
}

export const listSections = () => call<SectionInfo[]>("/sections");
export const listProfiles = () => call<Profile[]>("/profiles");
export const createProfile = (draft: ProfileDraft) =>
  call<Profile>("/profiles", { method: "POST", body: JSON.stringify(draft) });
export const updateProfile = (id: string, patch: Partial<Omit<ProfileDraft, "email">> & { is_active?: boolean }) =>
  call<Profile>(`/profiles/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });
export const deleteProfile = (id: string) =>
  call<void>(`/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
