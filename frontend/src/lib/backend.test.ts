import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch, onAccessDenied, onApiHealthChange, probeApiHealth } from "@/lib/backend";

describe("apiFetch health resilience", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(async () => {
    vi.useFakeTimers();
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await probeApiHealth();
  });

  afterEach(() => {
    vi.useRealTimers();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("ignores component AbortError without flipping health", async () => {
    const states: boolean[] = [];
    const unsub = onApiHealthChange((healthy) => states.push(healthy));

    globalThis.fetch = vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError"));
    await expect(apiFetch("/api/inbox/threads")).rejects.toThrow();

    expect(states[states.length - 1]).toBe(true);
    unsub();
  });

  it("does not immediately flip unhealthy on a single TimeoutError or sleep network glitch", async () => {
    const states: boolean[] = [];
    const unsub = onApiHealthChange((healthy) => states.push(healthy));

    globalThis.fetch = vi.fn().mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    await expect(apiFetch("/api/dashboard/pulse")).rejects.toThrow();
    expect(states[states.length - 1]).toBe(true);

    // One network glitch on wake followed by a successful /health/live keeps the banner hidden.
    globalThis.fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));

    await expect(apiFetch("/api/auth/me")).rejects.toThrow();
    expect(states[states.length - 1]).toBe(true);

    await vi.advanceTimersByTimeAsync(2000);
    expect(states[states.length - 1]).toBe(true);
    unsub();
  });

  it("marks unhealthy only after consecutive probe failures confirm down, then recovers", async () => {
    const states: boolean[] = [];
    const unsub = onApiHealthChange((healthy) => states.push(healthy));

    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiFetch("/api/inbox/threads")).rejects.toThrow();
    await expect(apiFetch("/api/inbox/threads")).rejects.toThrow();

    // First scheduled probe failure alone does not flip the banner yet.
    await vi.advanceTimersByTimeAsync(1600);
    expect(states[states.length - 1]).toBe(true);

    // Second failed /health/live confirmation flips unhealthy; one OK response restores healthy.
    await expect(probeApiHealth()).resolves.toBe(false);
    expect(states[states.length - 1]).toBe(false);

    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    await expect(probeApiHealth()).resolves.toBe(true);
    expect(states[states.length - 1]).toBe(true);
    unsub();
  });
});

describe("apiFetch access refusals", () => {
  const originalFetch = globalThis.fetch;
  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  const answer = (status: number) => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(null, { status }));
  };

  it("reports 401 and 403 from a data endpoint, so cached views can be dropped", async () => {
    const seen = vi.fn();
    const unsub = onAccessDenied(seen);
    answer(401);
    await apiFetch("/api/inbox/threads");
    answer(403);
    await apiFetch("/api/money/ledger");
    expect(seen).toHaveBeenCalledTimes(2);
    unsub();
  });

  it("stays quiet for successful calls and for the auth endpoints themselves", async () => {
    const seen = vi.fn();
    const unsub = onAccessDenied(seen);
    answer(200);
    await apiFetch("/api/inbox/threads");
    answer(401);
    await apiFetch("/api/auth/me");
    expect(seen).not.toHaveBeenCalled();
    unsub();
  });
});
