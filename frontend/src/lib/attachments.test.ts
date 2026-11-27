import { afterEach, describe, expect, it, vi } from "vitest";
import { approveInboxDraft, sendThreadReply, uploadThreadAttachment } from "./api";

describe("outbound thread attachments API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uploads a file via FormData to /api/inbox/threads/{caseId}/attachments", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        attachmentId: "att-123",
        filename: "lease.pdf",
        mimeType: "application/pdf",
        sizeBytes: 42,
        gmailAllowed: true,
        whatsappAllowed: true,
        driveQueued: true,
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const file = new File(["hello"], "lease.pdf", { type: "application/pdf" });
    const res = await uploadThreadAttachment("case-abc", file);

    expect(res.ok).toBe(true);
    expect(res.attachmentId).toBe("att-123");
    expect(res.driveQueued).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toContain("/api/inbox/threads/case-abc/attachments");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("forwards attachment_ids on approveInboxDraft and sendThreadReply", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, id: "act-1" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    await approveInboxDraft("act-1", "edit", "Hoi", undefined, ["att-1", "att-2"]);
    await sendThreadReply("case-1", "Zie bijlage", "gmail", undefined, ["att-3"]);

    expect(mockFetch).toHaveBeenCalledTimes(2);
    const approveBody = JSON.parse(mockFetch.mock.calls[0][1].body as string);
    expect(approveBody.attachment_ids).toEqual(["att-1", "att-2"]);

    const replyBody = JSON.parse(mockFetch.mock.calls[1][1].body as string);
    expect(replyBody.attachment_ids).toEqual(["att-3"]);
  });
});
