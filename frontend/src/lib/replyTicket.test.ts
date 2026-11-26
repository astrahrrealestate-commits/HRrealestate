import { describe, expect, it } from "vitest";
import { greetingName, replyTicket } from "./replyTicket";

const ticket = {
  tenantName: "Anouk Visser",
  tenantPhone: "anouk@example.test",
  tenantDraft: "Beste Anouk, de monteur komt.",
  contractorName: "Bouw BV",
};

describe("replyTicket", () => {
  it("names the sender of the latest mail, and drops a draft that greets someone else", () => {
    const shown = replyTicket(ticket, { senderName: "Jan de Vries", senderContact: "jan@example.test" });
    expect([shown.tenantName, shown.tenantPhone, shown.contractorName]).toEqual([
      "Jan de Vries",
      "jan@example.test",
      "Bouw BV",
    ]);
    expect(shown.tenantDraft).toBe("");
    expect(shown.tenantDraft).not.toContain("Anouk");
  });

  it("adds no generic draft when the ticket has none, and clears another tenant's draft without generic copy", () => {
    const empty = replyTicket({ ...ticket, tenantDraft: "" }, { senderName: "Jan", senderContact: "jan@example.test" });
    expect([empty.tenantName, empty.tenantDraft]).toEqual(["Jan", ""]);

    const cleared = replyTicket(
      { ...ticket, tenantDraft: "Beste Anouk, we bellen u morgen." },
      { senderName: "Jan de Vries", senderContact: "jan@example.test" }
    );
    expect(cleared.tenantDraft).toBe("");
    expect(cleared.tenantDraft).not.toContain("ontvangen");
  });

  it("keeps the ticket draft when the sender is the ticket's tenant", () => {
    const shown = replyTicket(ticket, { senderName: "Anouk Visser", senderContact: "anouk@example.test" });
    expect(shown).toEqual(ticket);
  });

  it("keeps the ticket when the thread names nobody", () => {
    expect(replyTicket(ticket, { senderName: "", senderContact: "" })).toEqual(ticket);
  });
});

describe("greetingName", () => {
  it.each([
    ["Jan de Vries", "Jan"],
    ["jan@example.test", "huurder"],
    ["+31612345678", "huurder"],
    ["Unknown sender", "huurder"],
    ["", "huurder"],
  ])("greets %j as %j", (name, expected) => {
    expect(greetingName(name)).toBe(expected);
  });
});
