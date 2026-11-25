import { describe, expect, it } from "vitest";
import { normalizeMessageWhitespace, parseQuotedText } from "@/components/inbox/ExpandableMessageBody";

describe("email whitespace normalization", () => {
  it("collapses excessive blank lines and invisible spacers without breaking quote splitting", () => {
    const raw =
      "Sunday, 22 November 2026\n\u00a0\n\u200b\n\n\n3 guests · 19:00 - 21:15\n\n\n\nReserved for Main\n\nOn Sun wrote:\n> old text";
    expect(normalizeMessageWhitespace("A\n\n\u00a0\n\n\nB")).toBe("A\n\nB");
    const { cleanBody, quotedText } = parseQuotedText(raw);
    expect(cleanBody).toBe("Sunday, 22 November 2026\n\n3 guests · 19:00 - 21:15\n\nReserved for Main");
    expect(quotedText).toContain("On Sun wrote:");
  });
});
