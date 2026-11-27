import { beforeEach, describe, expect, it } from "vitest";
import { clearViews, forgetView, readView, updateView, writeView } from "@/lib/viewCache";

describe("viewCache", () => {
  beforeEach(() => clearViews());

  it("returns nothing for a view that was never loaded", () => {
    expect(readView("inbox.threads")).toBeUndefined();
  });

  it("returns the last value written, so a page can paint before its refetch answers", () => {
    writeView("inbox.threads", [{ id: "case-1" }]);
    writeView("inbox.threads", [{ id: "case-2" }]);
    expect(readView("inbox.threads")).toEqual([{ id: "case-2" }]);
  });

  it("keeps falsy values apart from never loaded", () => {
    writeView("count", 0);
    expect(readView("count")).toBe(0);
  });

  it("drops everything on clear, so the next profile never sees this one's data", () => {
    writeView("money.ledger", [1]);
    writeView("inbox.threads", [2]);
    clearViews();
    expect(readView("money.ledger")).toBeUndefined();
    expect(readView("inbox.threads")).toBeUndefined();
  });

  it("records a value that goes back to where it started (November, October, November)", () => {
    updateView("money.month", "2026-10", "2026-11");
    updateView("money.month", "2026-11", "2026-11");
    expect(readView("money.month")).toBe("2026-11");
  });

  it("stacks functional updates on what is cached, falling back to the initial value", () => {
    updateView<number[]>("list", (prev) => [...prev, 1], []);
    updateView<number[]>("list", (prev) => [...prev, 2], []);
    expect(readView("list")).toEqual([1, 2]);
  });

  it("records a rollback that arrives after the page has gone", () => {
    const before = [{ status: "open" }];
    updateView("tickets", [{ status: "dispatched" }], before);
    updateView("tickets", before, before);
    expect(readView("tickets")).toBe(before);
  });

  it("forgets one view and keeps the rest", () => {
    writeView("comms.a", 1);
    writeView("comms.b", 2);
    forgetView("comms.a");
    expect(readView("comms.a")).toBeUndefined();
    expect(readView("comms.b")).toBe(2);
  });
});
