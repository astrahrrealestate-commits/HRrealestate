import { describe, expect, it } from "vitest";
import { profileKey } from "@/lib/profile";

const owner = { company_id: "c1", email: "a@example.test", isAdmin: false, sections: ["inbox", "money"] };

describe("profileKey", () => {
  it("is the same for the same access, whatever order sections arrive in", () => {
    expect(profileKey(owner)).toBe(profileKey({ ...owner, sections: ["money", "inbox"] }));
  });

  it("changes when a section is revoked, admin rights change or another person or company signs in", () => {
    expect(profileKey({ ...owner, sections: ["inbox"] })).not.toBe(profileKey(owner));
    expect(profileKey({ ...owner, isAdmin: true })).not.toBe(profileKey(owner));
    expect(profileKey({ ...owner, email: "b@example.test" })).not.toBe(profileKey(owner));
    expect(profileKey({ ...owner, company_id: "c2" })).not.toBe(profileKey(owner));
  });
});
