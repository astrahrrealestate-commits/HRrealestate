import { afterEach, describe, expect, it, vi } from "vitest";
import { enhanceThreadDraft } from "./api";

describe("enhanceThreadDraft", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("posts instruction and current_text to the thread enhance endpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          draftText: "Beste Jan, ik stuur vandaag een monteur.",
          variants: [
            "Beste Jan, ik stuur vandaag een monteur.",
            "Beste Jan, we plannen de monteur zo snel mogelijk in.",
          ],
          commitments: ["Send technician today"],
          sourcesUsed: ["Doc: Huurcontract"],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const res = await enhanceThreadDraft("case-123", {
      instruction: "Shorter",
      current_text: "Beste Jan, dank voor uw mail.",
    });

    expect(res.ok).toBe(true);
    expect(res.variants).toHaveLength(2);
    expect(res.sourcesUsed).toEqual(["Doc: Huurcontract"]);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toContain("/api/inbox/threads/case-123/enhance");
    expect((init as RequestInit).method).toBe("POST");
  });

  it("returns problem detail on validation error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Message has not finished analysis yet." }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      })
    );

    const res = await enhanceThreadDraft("case-123", {
      instruction: "Add clause",
      current_text: "Hi",
    });

    expect(res.ok).toBe(false);
    expect(res.problem).toBe("Message has not finished analysis yet.");
  });
});
