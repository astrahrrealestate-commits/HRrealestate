import { NextRequest } from "next/server";

const BACKEND_URL =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  "http://127.0.0.1:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();
  const headers: Record<string, string> = {
    "Content-Type": req.headers.get("content-type") || "application/json",
    Accept: "text/event-stream, application/json",
  };
  const auth = req.headers.get("authorization");
  if (auth) headers["authorization"] = auth;
  const cookie = req.headers.get("cookie");
  if (cookie) headers["cookie"] = cookie;

  const upstream = await fetch(`${BACKEND_URL}/api/agent/ask/stream`, {
    method: "POST",
    headers,
    body,
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    const errText = await upstream.text().catch(() => "Upstream error");
    return new Response(errText, {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
