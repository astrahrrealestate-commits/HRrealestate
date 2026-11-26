import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CategoryDeskData, CategorySummaryItem } from "@/lib/api";
import { pickInitialCategory, tabDisplay } from "@/lib/categories";
import { CategoryTabs } from "@/components/today/CategoryTabs";
import { CategoryDeskView } from "@/components/today/CategoryDesk";
import { DraftCommitments } from "@/components/inbox/DraftCommitments";
import { UnresponsiveRadarCard } from "@/components/today/UnresponsiveRadarCard";
import { Composer } from "@/components/inbox/Composer";
import { LanguageProvider } from "@/context/LanguageContext";

const SUMMARIES: CategorySummaryItem[] = [
  { category: "maintenance", label: "Maintenance", open_actions: 4, urgent: 1 },
  { category: "finance", label: "Finance", open_actions: 2, urgent: 3 },
  { category: "legal", label: "Legal", open_actions: 1, urgent: 1 },
  { category: "business", label: "Business", open_actions: 0, urgent: 0 },
  { category: "administration", label: "Administration", open_actions: 3, urgent: 0 },
  { category: "new_projects", label: "New projects", open_actions: 0, urgent: 0 },
];

describe("Today Category Desk", () => {
  it("selects the category with the most urgent actions on first load", () => {
    expect(pickInitialCategory(SUMMARIES)).toBe("finance");
  });

  it("keeps an empty category's tab without a count", () => {
    expect(tabDisplay(SUMMARIES[3])).toEqual({ label: "Business", count: null, hasUrgent: false });
    expect(tabDisplay(SUMMARIES[0])).toEqual({ label: "Maintenance", count: 4, hasUrgent: true });

    const html = renderToStaticMarkup(
      React.createElement(CategoryTabs, {
        summaries: SUMMARIES,
        activeCategory: "finance",
        onSelect: () => {},
      })
    );
    expect(html).toContain('data-category="business"');
    expect(html).not.toContain(">Business</span><span");
    expect(html).toContain("Maintenance");
    expect(html).toContain(">4<");
  });

  it("renders actions in server order with prepared text", () => {
    const desk: CategoryDeskData = {
      brief: "2 quotes above market, 1 reply ready to approve.",
      actions: [
        {
          id: "a-second-alphabetically",
          category: "finance",
          kind: "quote_review",
          title: "Counter Bouwbedrijf X quote",
          why: "€4.800 vs market €3.900–4.200",
          urgency: "high",
          due_at: null,
          case_id: "case-1",
          approval_id: null,
          prepared: "Prepared counter-offer citing 3 market references",
          target_url: "/inbox?thread=case-1",
        },
        {
          id: "a-first-alphabetically",
          category: "finance",
          kind: "approve_draft",
          title: "Approve reply to J. de Vries about the deposit",
          why: "draft ready",
          urgency: "normal",
          due_at: null,
          case_id: "case-2",
          approval_id: "appr-2",
          prepared: "Geachte J. de Vries, wij bevestigen de waarborgsom.",
          target_url: "/inbox?thread=case-2",
        },
      ],
    };

    const html = renderToStaticMarkup(
      React.createElement(CategoryDeskView, {
        summaries: SUMMARIES,
        activeCategory: "finance",
        desk,
        onSelectCategory: () => {},
        onAskAstra: () => {},
      })
    );

    const firstIdx = html.indexOf("Counter Bouwbedrijf X quote");
    const secondIdx = html.indexOf("Approve reply to J. de Vries about the deposit");
    expect(firstIdx).toBeGreaterThan(-1);
    expect(secondIdx).toBeGreaterThan(firstIdx);
    expect(html).toContain("Prepared counter-offer citing 3 market references");
    expect(html).toContain("Geachte J. de Vries, wij bevestigen de waarborgsom.");
    expect(html).toContain("Review draft");
    expect(html).toContain("Ask Astra");
  });
});

describe("Inbox composer commitments", () => {
  it("the composer lists a draft's commitments above Approve", () => {
    const commitmentsHtml = renderToStaticMarkup(
      React.createElement(DraftCommitments, {
        commitments: ["Send mechanic Friday morning", "Cap invoice at €250"],
      })
    );
    expect(commitmentsHtml).toContain("Send mechanic Friday morning");
    expect(commitmentsHtml).toContain("Cap invoice at €250");

    const composerHtml = renderToStaticMarkup(
      React.createElement(
        LanguageProvider,
        null,
        React.createElement(Composer, {
          threadKey: "t-1",
          channel: "whatsapp",
          draftText: "Beste Jan, monteur komt vrijdag.",
          drafts: [
            {
              id: "wd1",
              version: 1,
              label: "Draft 1",
              text: "Beste Jan, monteur komt vrijdag.",
              tone: "direct",
              channel: "whatsapp",
              recipientType: "tenant",
              recipientName: "Jan",
              commitments: ["Monteur komt vrijdagochtend", "Kostenplafond €250"],
            },
          ],
        })
      )
    );

    const commitmentPos = composerHtml.indexOf("Monteur komt vrijdagochtend");
    const approvePos = composerHtml.indexOf("Accept &amp; send");
    expect(commitmentPos).toBeGreaterThan(-1);
    expect(approvePos).toBeGreaterThan(commitmentPos);
  });
});

describe("Unresponsive radar offline behavior", () => {
  it("an offline radar shows the offline state, not demo rows", () => {
    const html = renderToStaticMarkup(
      React.createElement(UnresponsiveRadarCard, { items: [], isLive: false })
    );
    expect(html).toContain("Offline");
    expect(html).not.toContain("FastFix Loodgieters");
    expect(html).not.toContain("Anouk de Jong");
  });
});
