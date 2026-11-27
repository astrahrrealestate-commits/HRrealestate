import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 300;

/**
 * Dedicated proxy route for long-running AI draft enhancement (up to 3 minutes).
 * Bypasses Next.js's default `rewrites()` ~30s socket timeout for heavy RAG/web/DB enhancements.
 */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ caseId: string }> }
): Promise<NextResponse> {
  const { caseId } = await context.params;
  const backendHost = process.env.INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";
  const targetUrl = `${backendHost.replace(/\/+$/, "")}/api/inbox/threads/${encodeURIComponent(caseId)}/enhance`;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("accept", accept);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const clientHeader = request.headers.get("x-estateos-client");
  if (clientHeader) headers.set("x-estateos-client", clientHeader);

  const body = await request.text();

  try {
    const upstream = await fetch(targetUrl, {
      method: "POST",
      headers,
      body,
      signal: AbortSignal.timeout(185000),
    });
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") || "application/json",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "Enhance request timed out or could not reach the backend." },
      { status: 504 }
    );
  }
}
