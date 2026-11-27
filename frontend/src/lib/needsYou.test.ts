import { describe, expect, it, vi } from "vitest";
import { getPageNeedsYou, setPageNeedsYou, subscribeNeedsYou } from "@/lib/needsYou";

describe("page needs-you count", () => {
  it("gives the sidebar the open page's own count and takes it back when the page leaves", () => {
    const changed = vi.fn();
    const unsubscribe = subscribeNeedsYou(changed);
    setPageNeedsYou(4);
    expect(getPageNeedsYou()).toBe(4);
    setPageNeedsYou(null);
    expect(getPageNeedsYou()).toBeNull();
    expect(changed).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});
