import { describe, expect, it } from "vitest";
import { getContactDisplayName } from "./threadSanitizer";

describe("getContactDisplayName", () => {
  it.each(["Harjot Singh", "Suryansh", "Tenant", "Admin"])("keeps the sender name the server gave: %s", (name) => {
    expect(
      getContactDisplayName({ senderName: name, senderContact: "jan@example.test" }),
    ).toBe(name);
  });

  it("shows the address, never a guessed name, when there is no name", () => {
    expect(getContactDisplayName({ senderName: "  ", senderContact: "jan.de.vries@example.test" })).toBe(
      "jan.de.vries@example.test",
    );
  });

  it("says the sender is unknown when there is neither", () => {
    expect(getContactDisplayName({})).toBe("Unknown sender");
  });
});
