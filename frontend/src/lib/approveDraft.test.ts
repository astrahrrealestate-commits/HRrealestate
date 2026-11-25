import { describe, expect, it, vi } from "vitest";
import { approveOrReply } from "./approveDraft";

const sent = { ok: true, status: "approved", message: "queued" };

describe("approveOrReply", () => {
  it.each(["already_decided", "rejected", "held"])(
    "never sends the text another way when approving answers %s",
    async (status) => {
      const reply = vi.fn(async () => sent);
      const result = await approveOrReply({
        approve: async () => ({ ok: status === "already_decided", status, message: "m" }),
        reply,
      });
      expect(reply).not.toHaveBeenCalled();
      expect(result.ok).toBe(false);
    },
  );

  it("returns the approval result when it succeeds", async () => {
    const reply = vi.fn(async () => sent);
    const result = await approveOrReply({ approve: async () => sent, reply });
    expect([result, reply.mock.calls.length]).toEqual([sent, 0]);
  });

  it("sends a typed reply only when there is no approval to decide", async () => {
    const reply = vi.fn(async () => sent);
    expect(await approveOrReply({ approve: undefined, reply })).toEqual(sent);
    expect(reply).toHaveBeenCalledTimes(1);
  });
});
