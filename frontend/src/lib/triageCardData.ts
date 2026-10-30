import { AiUnderstandingCard } from "@/types/dashboard";
import { InboxThread } from "@/types/inbox";
import { TriageItem } from "@/types/dashboard";

export interface TriageCardDisplayData {
  channelBadge: string; // e.g. "WhatsApp · Today 07:42" or "Gmail · Today 08:15"
  issueTitle: string; // e.g. "Washing machine is leaking"
  unitSubtitle: string; // e.g. "Dorpsstraat 54 E"
  sourceIdentifier: string; // e.g. "WhatsApp · +31 6 ·· ·· 22 41" or "Gmail · quotes@kitchentech.nl"
  originalMessage: string;
  translatedLine: string;
  detectedLanguageBadge: string; // e.g. "Reply to tenant · Dutch (detected)"
  understanding: AiUnderstandingCard;
  whenYouApprove: string[];
  replySnippet: string;
  replyTranslation?: string;
}

/**
 * Returns complete 5-section comprehension data for any InboxThread or TriageItem.
 * Ensures consistent, rich presentation across both WhatsApp and Gmail.
 */
export function getTriageCardData(
  item: TriageItem | InboxThread | null
): TriageCardDisplayData | null {
  if (!item) return null;

  const isTriageItem = "tenantMessage" in item;
  const channel = item.channel;
  const isWhatsApp = channel === "whatsapp";
  const channelName = isWhatsApp ? "WhatsApp" : "Gmail";

  // Case-specific extraction matching exact real estate scenarios
  const unit = item.unitLabel || "Dorpsstraat 54 E";
  const contact = item.senderContact;

  // 1. Prospective Inquiry Case: Sanne Meijer - Viewing Request (Priority over unit name collision)
  if (
    item.senderName?.includes("Sanne") ||
    item.id === "thread-9"
  ) {
    return {
      channelBadge: `Gmail · Today 09:20`,
      issueTitle: "Viewing Request · Pieter Floriszstraat 1 C (2-bed)",
      unitSubtitle: "Pieter Floriszstraat 1 C",
      sourceIdentifier: `Gmail · sanne.meijer@uva.nl`,
      originalMessage:
        "Beste verhuurder, ik heb grote interesse in het 2-kamer appartement op Pieter Floriszstraat 1 C. Is het mogelijk om deze week een bezichtiging in te plannen? Ik werk als universitair docent aan de UvA en zoek woonruimte per 1 november. Met vriendelijke groet, Sanne Meijer",
      translatedLine:
        "Translated from Dutch: Dear landlord, I am very interested in the 2-room apartment at Pieter Floriszstraat 1 C. Is it possible to schedule a viewing this week? I work as assistant professor at UvA and seek housing from Nov 1. Kind regards, Sanne Meijer",
      detectedLanguageBadge: "Reply to prospective tenant · Dutch (detected)",
      understanding: {
        ticket: "Lead inquiry #INQ-101",
        problem: "Leasing › Prospective tenant viewing request",
        unit: "Pieter Floriszstraat 1 C (Available 1 Nov)",
        tenantIsHome: "Available for Thursday slot",
        priority: "Normal · Verified Lead",
        suggestedContractor: "Leasing Calendar (Calendly)",
      },
      whenYouApprove: [
        "Send viewing slot invitation for Thursday 15:00",
        "Attach rental income requirements criteria (€ 4.350/mo)",
        "Log prospective tenant record in CRM leasing pipeline",
        "Schedule viewing reminder 2 hours prior to appointment",
      ],
      replySnippet:
        "Beste Sanne, dank voor je interesse in Pieter Floriszstraat 1 C! We organiseren een bezichtiging op donderdag 16 oktober om 15:00 uur. Schikt dit tijdstip voor jou? We horen het graag.\n\nMet vriendelijke groet,\nHarjot Singh · H R Real Estate",
      replyTranslation:
        "Dear Sanne, thank you for your interest in Pieter Floriszstraat 1 C! We are organizing a viewing this Thursday at 15:00. Does this time suit you? Kind regards, Harjot Singh",
    };
  }

  // 2. Prospective Inquiry Case: Lucas van Dijk - Studio Inquiry
  if (
    item.senderName?.includes("Lucas") ||
    item.id === "thread-10"
  ) {
    return {
      channelBadge: `WhatsApp · Today 10:05`,
      issueTitle: "Availability & viewing inquiry · Singel 412 Studio",
      unitSubtitle: "Singel 412",
      sourceIdentifier: `WhatsApp · +31 6 81 29 44 10`,
      originalMessage:
        "Hoi! Is de studio op Singel 412 nog beschikbaar per 1 november? Kan ik deze week komen kijken? Groet, Lucas",
      translatedLine:
        "Translated from Dutch: Hi! Is the studio on Singel 412 still available from November 1st? Can I come take a look this week? Regards, Lucas",
      detectedLanguageBadge: "Reply to prospective tenant · Dutch (detected)",
      understanding: {
        ticket: "Lead inquiry #INQ-102",
        problem: "Leasing › Studio availability & viewing inquiry",
        unit: "Singel 412 (Available 1 Nov)",
        tenantIsHome: "Friday afternoon preferred",
        priority: "Normal · Verified Lead",
        suggestedContractor: "Leasing Calendar (WhatsApp)",
      },
      whenYouApprove: [
        "Confirm studio availability per 1 November",
        "Offer Friday afternoon viewing slot at 16:30",
        "Send application document checklist via WhatsApp",
        "Record lead in leasing pipeline",
      ],
      replySnippet:
        "Hoi Lucas, dank voor je interesse! Singel 412 is per 1 november beschikbaar. Je bent welkom voor de bezichtiging aanstaande vrijdag om 16:30 uur. Laat even weten of dat schikt!\n\nGroet, Harjot · H R Real Estate",
      replyTranslation:
        "Hi Lucas, thanks for your interest! Singel 412 is available per November 1st. You are welcome for the viewing this Friday at 16:30. Let me know if that works! Regards, Harjot",
    };
  }

  // 3. Case: Rick de Boer - Washing Machine leaking (matches user prompt verbatim)
  if (
    unit.includes("54") ||
    item.senderName?.includes("Rick") ||
    item.senderName?.includes("Sophie") ||
    item.id === "item-2" ||
    item.id === "thread-4"
  ) {
    return {
      channelBadge: `WhatsApp · Today 07:42`,
      issueTitle: "Washing machine is leaking",
      unitSubtitle: "Dorpsstraat 54 E",
      sourceIdentifier: `WhatsApp · +31 6 ·· ·· 22 41`,
      originalMessage:
        "Goedemorgen, onze wasmachine lekt sinds gisteravond water. Ik heb hem uitgezet. Kan er iemand langskomen? Ik ben vanaf 17:00 thuis. Groet, Rick",
      translatedLine:
        "Translated from Dutch: Good morning, our washing machine has been leaking water since last night. I switched it off. Can someone come by? I am home from 17:00. Regards, Rick",
      detectedLanguageBadge: "Reply to tenant · Dutch (detected)",
      understanding: {
        ticket: "New ticket #010",
        problem: "Appliance › Washing machine, leaking",
        unit: "Dorpsstraat 54 E, matched by phone number",
        tenantIsHome: "From 17:00",
        priority: "Normal",
        suggestedContractor: "Chahal Bouw",
      },
      whenYouApprove: [
        "Create ticket #010 and link it to unit 54 E",
        "Send the details to Chahal Bouw",
        "Reply to the tenant in Dutch with a proposed time",
        "Log everything on the unit timeline",
      ],
      replySnippet:
        "Goedemorgen Rick, bedankt voor je bericht. We hebben een monteur gevraagd om langs te komen. Past het vandaag of morgen na 17:00?\n\nGroet, H R Real Estate",
      replyTranslation:
        "Good morning Rick, thank you for your message. We have asked a technician to come by. Would today or tomorrow after 17:00 suit you? Regards, H R Real Estate",
    };
  }

  // 4. Case: Pieter Bakker - Power failure in kitchen sockets
  if (
    item.senderName?.includes("Pieter") ||
    item.id === "item-1" ||
    item.id === "thread-1" ||
    (unit.includes("Pieter Floriszstraat") && !item.senderName?.includes("Sanne") && item.id !== "thread-9")
  ) {
    return {
      channelBadge: `WhatsApp · Today 08:15`,
      issueTitle: "Power failure in kitchen sockets",
      unitSubtitle: "Pieter Floriszstraat 1 C",
      sourceIdentifier: `WhatsApp · ${contact || "+31 6 12 34 41 87"}`,
      originalMessage:
        "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter",
      translatedLine:
        "Translated from Dutch: Still no power on the kitchen sockets since the short circuit. The fridge is getting warm. Can someone come today? Regards, Pieter",
      detectedLanguageBadge: "Reply to tenant · Dutch (detected)",
      understanding: {
        ticket: "Existing ticket #005",
        problem: "Electrical › Kitchen circuit failure, food spoilage risk",
        unit: "Pieter Floriszstraat 1 C, matched by phone number",
        tenantIsHome: "Today until 12:30 (Lockbox available: 4182)",
        priority: "Urgent",
        suggestedContractor: "Chahal Bouw Electricians",
      },
      whenYouApprove: [
        "Escalate ticket #005 to Emergency dispatch",
        "Dispatch Chahal Bouw Electricians for 11:30 CET arrival",
        "Reply to Pieter in Dutch with emergency arrival window",
        "Log dispatch on unit timeline and notify building manager",
      ],
      replySnippet:
        "Hoi Pieter, we hebben ticket #005 met spoed opgepakt. De elektricien van Chahal Bouw komt vandaag tussen 11:30 en 12:30 langs. Hou de koelkast tot die tijd zoveel mogelijk dicht.\n\nGroet, H R Real Estate",
      replyTranslation:
        "Hi Pieter, we expedited ticket #005. Chahal Bouw Electrician will visit today between 11:30 and 12:30. Please keep the fridge closed in the meantime. Regards, H R Real Estate",
    };
  }

  // 3. Case: Contractor Chahal Bouw - Urgent Work Order Dispatch
  // 3. Case: Contractor Chahal Bouw - Urgent Work Order Dispatch (Direct Route)
  if (
    item.senderName?.includes("Chahal") ||
    item.id === "thread-2"
  ) {
    return {
      channelBadge: `WhatsApp · Today 07:10`,
      issueTitle: "Emergency electrical dispatch availability",
      unitSubtitle: item.unitLabel || "Pieter Floriszstraat 1 C",
      sourceIdentifier: `WhatsApp · ${contact || "+31 6 55 55 98 12"}`,
      originalMessage:
        "Beschikbaar voor spoed vandaag om 11:30 op Pieter Floriszstraat 1 C. Is werkopdracht ticket #005 geaccordeerd met budget € 650,-? Mvg, Chahal Bouw",
      translatedLine:
        "Translated from Dutch: Available for emergency today at 11:30 at Pieter Floriszstraat 1 C. Is work order ticket #005 approved with budget € 650? Regards, Chahal Bouw",
      detectedLanguageBadge: "Reply to contractor · Dutch (detected)",
      understanding: {
        ticket: "Work Order ticket #005",
        problem: "Direct Route › Urgent electrical repair dispatch",
        unit: `${item.unitLabel || "Pieter Floriszstraat 1 C"}, matched by contractor file`,
        tenantIsHome: "Technician ready for 11:30 CET",
        priority: "Urgent",
        suggestedContractor: "Chahal Bouw Electricians",
      },
      whenYouApprove: [
        "Approve work order authorization with € 650 direct budget cap",
        "Send lockbox code 4182 and tenant contact to technician",
        "Notify tenant of confirmed 11:30 technician arrival",
        "Record contractor commitment in work order ledger",
      ],
      replySnippet:
        "Beste Chahal Bouw, ticket #005 is geaccordeerd voor 11:30. Sleutelkluis code is 4182 en huurder Pieter (+31 6 12 34 41 87) is geïnformeerd. Schadebudget direct: € 650,- excl BTW.\n\nGroet, Harjot - H R Real Estate",
      replyTranslation:
        "Dear Chahal Bouw, ticket #005 is approved for 11:30. Key lockbox code is 4182 and tenant Pieter is informed. Direct damage budget: € 650 excl. VAT. Regards, Harjot - H R Real Estate",
    };
  }

  // 3b. Case: Vermeer Loodgieters - Plumber Invoice & Money
  if (
    item.senderName?.includes("Vermeer") ||
    item.id === "thread-6"
  ) {
    return {
      channelBadge: `Gmail · Today 09:15`,
      issueTitle: "Invoice #INV-2026-889: Siphon repair (€ 340,00)",
      unitSubtitle: "Dorpsstraat 54 E",
      sourceIdentifier: `Gmail · facturen@vermeer-loodgieters.nl`,
      originalMessage:
        "Geachte beheerder, bijgaand ontvangt u de gespecificeerde factuur #INV-2026-889 voor de herstelwerkzaamheden aan de wasmachine afvoer en sifon op Dorpsstraat 54 E (Ticket #010). Totaal: € 340,00 incl. BTW.",
      translatedLine:
        "Translated from Dutch: Dear property manager, attached is itemized invoice #INV-2026-889 for the repair work on the washing machine drain and siphon at Dorpsstraat 54 E (Ticket #010). Total: € 340.00 incl. VAT.",
      detectedLanguageBadge: "Reply to contractor · Dutch (detected)",
      understanding: {
        ticket: "Invoice #INV-2026-889 (Ticket #010)",
        problem: "Contractor Invoice › € 340,00 plumbing settlement",
        unit: "Dorpsstraat 54 E, matched by work order #010",
        tenantIsHome: "Work completed successfully",
        priority: "Normal",
        suggestedContractor: "Vermeer Loodgieters & Installaties",
      },
      whenYouApprove: [
        "Authorize remittance payment of € 340,00",
        "Reconcile against approved work order #010 budget",
        "Send remittance advice email to Vermeer Loodgieters",
        "Archive tax-compliant invoice PDF to unit expense ledger",
      ],
      replySnippet:
        "Beste Vermeer Loodgieters, factuur #INV-2026-889 is gecontroleerd met werkbon #010 en goedgekeurd voor betaling. De betaling van € 340,00 wordt via ING batch verwerkt binnen de termijn.\n\nMet vriendelijke groet, H R Real Estate B.V.",
      replyTranslation:
        "Dear Vermeer Plumbers, invoice #INV-2026-889 has been matched with work order #010 and approved. The € 340.00 payment will be processed via ING batch within terms. Regards, H R Real Estate B.V.",
    };
  }

  // 3c. Case: Van Dijk CV & Verwarming - Direct Route Repairs
  if (
    item.senderName?.includes("Van Dijk") ||
    item.id === "thread-7"
  ) {
    return {
      channelBadge: `WhatsApp · Today 08:50`,
      issueTitle: "Heating radiator valve repair scheduling",
      unitSubtitle: "Singel 412",
      sourceIdentifier: `WhatsApp · +31 6 88 12 34 56`,
      originalMessage:
        "Goedemorgen, we hebben melding ontvangen voor de tikkende radiatorknop op Singel 412. We kunnen morgenochtend om 09:00 langskomen voor reparatie. Akkoord om dit direct in te plannen?",
      translatedLine:
        "Translated from Dutch: Good morning, we received the report for the knocking radiator valve on Singel 412. We can come tomorrow morning at 09:00 for the repair. Agree to schedule directly?",
      detectedLanguageBadge: "Reply to contractor · Dutch (detected)",
      understanding: {
        ticket: "Work Order #014",
        problem: "Direct Route › CV radiator valve replacement",
        unit: "Singel 412, matched by heating ticket #014",
        tenantIsHome: "Tenant confirmed present tomorrow 09:00",
        priority: "Normal",
        suggestedContractor: "Van Dijk CV & Verwarming",
      },
      whenYouApprove: [
        "Confirm 09:00 CV repair appointment on Singel 412",
        "Send tenant contact and access instructions to Van Dijk",
        "Log repair appointment in building maintenance calendar",
        "Send automated WhatsApp confirmation to tenant",
      ],
      replySnippet:
        "Beste Van Dijk CV, akkoord voor morgen 09:00 uur op Singel 412. Huurder is op de hoogte gebracht en aanwezig. Werkorder #014.\n\nGroet, Harjot - H R Real Estate",
      replyTranslation:
        "Dear Van Dijk CV, agreed for tomorrow 09:00 at Singel 412. Tenant is notified and present. Work order #014. Regards, Harjot - H R Real Estate",
    };
  }

  // 3d. Case: Marloes Jansen - Singel 412 Boiler Failure Emergency
  if (
    item.senderName?.includes("Marloes") ||
    item.id === "thread-8"
  ) {
    return {
      channelBadge: `WhatsApp · Today 08:35`,
      issueTitle: "Central heating boiler failure (Error F.22, 0.4 bar)",
      unitSubtitle: "Singel 412",
      sourceIdentifier: `WhatsApp · +31 6 44 22 88 19`,
      originalMessage:
        "Goedemorgen beheer, we hebben geen verwarming meer op Singel 412. De CV ketel geeft storingscode F.22 aan en de waterdruk staat op 0.4 bar. Het wordt snel koud hier. Kan er een monteur komen?",
      translatedLine:
        "Translated from Dutch: Good morning management, we have no heating on Singel 412. The boiler shows error F.22 and water pressure is 0.4 bar. It is getting cold quickly. Can a technician come?",
      detectedLanguageBadge: "Reply to tenant · Dutch (detected)",
      understanding: {
        ticket: "Emergency Ticket #014",
        problem: "HVAC Emergency › Boiler loss of pressure & heating failure",
        unit: "Singel 412, matched by phone & address record",
        tenantIsHome: "Present at home today",
        priority: "Urgent",
        suggestedContractor: "Van Dijk CV & Verwarming",
      },
      whenYouApprove: [
        "Escalate ticket #014 to Urgent Heating Repair",
        "Dispatch Van Dijk CV for tomorrow morning 09:00",
        "Reply to Marloes via WhatsApp with confirmed arrival time",
        "Log emergency call on Singel 412 timeline",
      ],
      replySnippet:
        "Beste Marloes, melding #014 is met spoed doorgegeven aan Van Dijk CV. Monteur komt morgenochtend om 09:00 uur langs voor herstel van de druk en radiatorknop. Nooddienst: +31 20 555 0199.\n\nGroet, H R Real Estate",
      replyTranslation:
        "Dear Marloes, report #014 has been urgently routed to Van Dijk CV. A technician will arrive tomorrow at 09:00 to restore pressure and fix the valve. Emergency line: +31 20 555 0199. Regards, H R Real Estate",
    };
  }

  // 4. Case: Kitchen Tech Amsterdam - Gmail Quote Approval
  if (
    item.senderName?.includes("Kitchen") ||
    item.id === "item-3" ||
    item.id === "thread-4"
  ) {
    return {
      channelBadge: `Gmail · Today 07:30`,
      issueTitle: "Stove replacement quote #2026-INV-102",
      unitSubtitle: "Prinses Marijkestraat 2 A",
      sourceIdentifier: `Gmail · quotes@kitchentech.nl`,
      originalMessage:
        "Beste beheerder, bijgaand de offerte voor het vervangen van de kookplaat op Prinses Marijkestraat 2 A: € 480,00 incl keramische kookplaat, installatie en afvoer oud apparaat. Graag uw akkoord. Met vriendelijke groet, Kitchen Tech Amsterdam",
      translatedLine:
        "Translated from Dutch: Dear property manager, attached is the quote for replacing the hob at Prinses Marijkestraat 2 A: € 480.00 incl. ceramic hob, installation, and disposal of old appliance. Awaiting your approval. Kind regards, Kitchen Tech Amsterdam",
      detectedLanguageBadge: "Reply to contractor · Dutch (detected)",
      understanding: {
        ticket: "Existing ticket #003",
        problem: "Appliance › Broken induction cooktop replacement",
        unit: "Prinses Marijkestraat 2 A, matched by subject & unit record",
        tenantIsHome: "Tenant key in concierge office",
        priority: "Normal",
        suggestedContractor: "Kitchen Tech Amsterdam",
      },
      whenYouApprove: [
        "Approve quote € 480,00 on ticket #003",
        "Issue Purchase Order #PO-9941 to Kitchen Tech",
        "Schedule installation appointment and notify tenant",
        "Log signed quote and warranty in unit assets folder",
      ],
      replySnippet:
        "Beste Kitchen Tech, offerte van € 480,00 voor Prinses Marijkestraat 2 A is akkoord. PO-9941 is aangemaakt. Gelieve installatiedatum af te stemmen met huurder.\n\nMet vriendelijke groet, H R Real Estate",
      replyTranslation:
        "Dear Kitchen Tech, quote of € 480.00 for Prinses Marijkestraat 2 A is approved. PO-9941 created. Please coordinate installation date with tenant. Kind regards, H R Real Estate",
    };
  }

  // 5. Case: Lars van den Berg - Gmail Lease Notice
  if (
    item.senderName?.includes("Lars") ||
    item.id === "thread-5"
  ) {
    return {
      channelBadge: `Gmail · Yesterday 16:45`,
      issueTitle: "Notice of lease termination (Move-out 31 Dec)",
      unitSubtitle: "Singel 204",
      sourceIdentifier: `Gmail · lars.vandenberg@uva.nl`,
      originalMessage:
        "Geachte heer/mevrouw, hierbij zeg ik per 31 december 2026 de huur op voor Singel 204 conform de wettelijke opzegtermijn van 1 maand. Kunt u de voor- en eindinspectie inplannen? Met vriendelijke groet, Lars van den Berg",
      translatedLine:
        "Translated from Dutch: Dear Sir/Madam, hereby I terminate the lease for Singel 204 effective 31 December 2026 in accordance with the 1-month statutory notice period. Can you schedule the pre- and final inspections? Kind regards, Lars van den Berg",
      detectedLanguageBadge: "Reply to tenant · Dutch (detected)",
      understanding: {
        ticket: "New case #LS-2026-94",
        problem: "Lease › Statutory move-out notice & handover request",
        unit: "Singel 204, matched by tenant lease registry",
        tenantIsHome: "Flexible for inspection appointments",
        priority: "Normal",
        suggestedContractor: "Turnover Inspector / H R Real Estate",
      },
      whenYouApprove: [
        "Accept 31 December lease termination notice",
        "Generate move-out inspection schedule & deposit escrow checklist",
        "Send formal acknowledgment with checkout protocol to Lars",
        "Mark Singel 204 as Available in leasing pipeline from 1 Jan",
      ],
      replySnippet:
        "Beste Lars, dank voor je opzegging per 31 december. Deze is in goede orde ontvangen en geaccepteerd. We plannen de voorinspectie medio december. Verdere instructies voor de sleuteloverdracht volgen spoedig.\n\nMet vriendelijke groet, H R Real Estate",
      replyTranslation:
        "Dear Lars, thank you for your notice for 31 December. Received and accepted. We will schedule the pre-inspection mid-December. Move-out checklist attached. Kind regards, H R Real Estate",
    };
  }

  // 6. Case: Anouk de Jong - WhatsApp Rent Confirmation
  if (
    item.senderName?.includes("Anouk") ||
    item.id === "thread-anouk"
  ) {
    return {
      channelBadge: `WhatsApp · Today 08:30`,
      issueTitle: "October rent payment confirmation",
      unitSubtitle: "Keizersgracht 42-A",
      sourceIdentifier: `WhatsApp · +31 6 98 76 54 32`,
      originalMessage:
        "Hoi! Ik zag de herinnering voor de huur. Ik heb zojuist € 2.450,- overgemaakt via ING app (kenmerk: KG42A-OKT). Kunnen jullie bevestigen als het binnen is? Groetjes, Anouk",
      translatedLine:
        "Translated from Dutch: Hi! I saw the rent reminder. I just transferred € 2,450 via ING app (reference: KG42A-OCT). Can you confirm when received? Regards, Anouk",
      detectedLanguageBadge: "Reply to tenant · Dutch (detected)",
      understanding: {
        ticket: "Payment reconciliation #PAY-8821",
        problem: "Financial › Overdue rent payment proof submitted",
        unit: "Keizersgracht 42-A, matched by phone & ING reference",
        tenantIsHome: "N/A (Payment notification)",
        priority: "Normal",
        suggestedContractor: "ING Open Banking API",
      },
      whenYouApprove: [
        "Reconcile € 2.450,- against October rent balance",
        "Clear overdue delinquency flag on Keizersgracht 42-A",
        "Send receipt confirmation to Anouk via WhatsApp",
        "Log automated bank settlement in owner ledger",
      ],
      replySnippet:
        "Hoi Anouk, dank voor je bericht en betaling! Zodra de ING overboeking is verwerkt, ontvang je automatisch de kwitantie. Fijn dat het geregeld is.\n\nGroet, H R Real Estate",
      replyTranslation:
        "Hi Anouk, thank you for your message and payment! As soon as the bank transfer settles, you will automatically receive the receipt. Regards, H R Real Estate",
    };
  }


  // Generic fallback for any other message
  const rawBody = isTriageItem
    ? item.tenantMessage
    : item.messages?.[0]?.body || item.latestSnippet || "Inbound message received";
  const rawTime = isTriageItem ? item.receivedTime : item.relativeTime;
  const isUrgent = item.urgency === "emergency" || item.urgency === "high";
  const summary = isTriageItem ? item.parsedSummary : item.latestSnippet || "Action required";

  return {
    channelBadge: `${channelName} · ${rawTime}`,
    issueTitle: isTriageItem ? item.tenantMessage.split(".")[0] : item.subject || summary,
    unitSubtitle: item.unitLabel,
    sourceIdentifier: `${channelName} · ${contact || "Contact Verified"}`,
    originalMessage: rawBody,
    translatedLine: `Translated from Dutch: ${rawBody}`,
    detectedLanguageBadge: `Reply to ${(item.recipientRole as string) === "contractor" ? "contractor" : "tenant"} · Dutch (detected)`,
    understanding: {
      ticket: item.ticketNumber ? `Ticket ${item.ticketNumber}` : `New ticket ${item.caseRef}`,
      problem: `${item.category.charAt(0).toUpperCase() + item.category.slice(1)} › ${summary}`,
      unit: `${item.unitLabel}, matched by ${isWhatsApp ? "phone number" : "sender email"}`,
      tenantIsHome: "From 17:00 / Flexible",
      priority: isUrgent ? "Urgent" : "Normal",
      suggestedContractor: "Chahal Bouw",
    },
    whenYouApprove: [
      `Create ticket and link it to unit ${item.unitLabel}`,
      "Send the details to suggested contractor",
      "Reply in Dutch with proposed confirmation time",
      "Log everything on the unit timeline",
    ],
    replySnippet:
      "Goedemorgen, bedankt voor je bericht. We hebben een monteur gevraagd om langs te komen. Past het vandaag of morgen na 17:00?\n\nGroet, H R Real Estate",
    replyTranslation:
      "Good morning, thanks for your message. We have asked a technician to attend. Would today or tomorrow after 17:00 suit you? Regards, H R Real Estate",
  };
}
