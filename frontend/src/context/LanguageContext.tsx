"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from "react";

export type Language = "en" | "nl";

export interface Translations {
  [key: string]: {
    en: string;
    nl: string;
  };
}

export const DICTIONARY: Translations = {
  // Navigation & Workspace
  "nav.workspace": { en: "WORKSPACE", nl: "WERKPLEK" },
  "nav.dashboard": { en: "Dashboard", nl: "Overzicht" },
  "nav.today_badge": { en: "Today", nl: "Vandaag" },
  "nav.messages": { en: "Messages", nl: "Berichten" },
  "nav.properties": { en: "Properties", nl: "Panden" },
  "nav.tenants": { en: "Tenants", nl: "Huurders" },
  "nav.contacts": { en: "Contacts", nl: "Contacten" },
  "nav.maintenance": { en: "Maintenance", nl: "Onderhoud" },
  "nav.money": { en: "Money", nl: "Financiën" },
  "nav.reports": { en: "Reports", nl: "Rapporten" },
  "nav.settings": { en: "Settings", nl: "Instellingen" },
  "nav.knowledge_base": { en: "Knowledge Base", nl: "Kennisbank" },
  "nav.connections": { en: "Connections", nl: "Koppelingen" },
  "nav.live": { en: "Live", nl: "Actief" },
  "nav.search_placeholder": { en: "Search...", nl: "Zoeken..." },
  "nav.sign_out": { en: "Sign out", nl: "Uitloggen" },
  "nav.owner": { en: "Owner", nl: "Eigenaar" },
  "nav.manager": { en: "Manager", nl: "Beheerder" },

  // TopCommandBar
  "topbar.super_agent": { en: "EstateOS Super Agent", nl: "EstateOS Super Agent" },
  "topbar.control_center": { en: "Conversational Control Center", nl: "Gespreksbeheercentrum" },
  "topbar.main_dashboard": { en: "Main Dashboard", nl: "Hoofddashboard" },
  "Main Dashboard": { en: "Main Dashboard", nl: "Hoofddashboard" },
  "topbar.sync": { en: "Sync", nl: "Synchroniseren" },
  "topbar.syncing": { en: "Syncing...", nl: "Synchroniseren..." },
  "topbar.agent_active": { en: "Active", nl: "Actief" },
  "topbar.agent_core": { en: "Super Agent", nl: "Super Agent" },

  // Page Titles
  "Maintenance": { en: "Maintenance", nl: "Onderhoud" },
  "Money & Ledger": { en: "Money & Ledger", nl: "Financiën & Grootboek" },
  "Money": { en: "Money", nl: "Financiën" },
  "Financial Control": { en: "Financial Control", nl: "Financieel Overzicht" },
  "Tenants Directory": { en: "Tenants Directory", nl: "Huurdersoverzicht" },
  "Tenants": { en: "Tenants", nl: "Huurders" },
  "Properties & Units": { en: "Properties & Units", nl: "Panden & Eenheden" },
  "Properties Portfolio": { en: "Properties Portfolio", nl: "Vastgoedportefeuille" },
  "Properties": { en: "Properties", nl: "Panden" },
  "Inbox & Communications": { en: "Inbox & Communications", nl: "Inbox & Communicatie" },
  "Inbox": { en: "Inbox", nl: "Inbox" },
  "Contacts Directory": { en: "Contacts Directory", nl: "Contactpersonen" },
  "Contacts": { en: "Contacts", nl: "Contacten" },
  "Settings": { en: "Settings", nl: "Instellingen" },
  "Reports & Knowledge": { en: "Reports & Knowledge", nl: "Rapporten & Kennisbank" },
  "Reports": { en: "Reports", nl: "Rapporten" },

  // Tabs & Filters
  "Open": { en: "Open", nl: "Open" },
  "Needs approval": { en: "Needs approval", nl: "Goedkeuring vereist" },
  "Done": { en: "Done", nl: "Voltooid" },
  "All": { en: "All", nl: "Alles" },
  "All statuses": { en: "All statuses", nl: "Alle statussen" },
  "Dispatched": { en: "Dispatched", nl: "Verzonden" },
  "Scheduled": { en: "Scheduled", nl: "Ingepland" },
  "Completed": { en: "Completed", nl: "Voltooid" },
  "Pending": { en: "Pending", nl: "In afwachting" },
  "Waiting": { en: "Waiting", nl: "In afwachting" },
  "Overview": { en: "Overview", nl: "Overzicht" },
  "Receivables": { en: "Receivables", nl: "Vorderingen" },
  "Payables": { en: "Payables", nl: "Te betalen" },
  "Overdue": { en: "Overdue", nl: "Achterstallig" },
  "Up to date": { en: "Up to date", nl: "Bijgewerkt" },
  "Occupied": { en: "Occupied", nl: "Verhuurd" },
  "Vacant": { en: "Vacant", nl: "Leegstaand" },
  "Drafted": { en: "Drafted", nl: "Concepten" },
  "Unread": { en: "Unread", nl: "Ongelezen" },
  "All Tenants": { en: "All Tenants", nl: "Alle Huurders" },
  "Settled / Paid": { en: "Settled / Paid", nl: "Voldaan / Betaald" },
  "Overdue Arrears": { en: "Overdue Arrears", nl: "Achterstallige Huur" },
  "Scheduled Rent": { en: "Scheduled Rent", nl: "Geplande Huur" },
  "Collected Rent": { en: "Collected Rent", nl: "Geïncasseerde Huur" },
  "Portfolio Occupancy": { en: "Portfolio Occupancy", nl: "Portefeuille Bezetting" },
  "Settled Rent": { en: "Settled Rent", nl: "Voldane Huur" },
  "Scheduled Target": { en: "Scheduled Target", nl: "Gepland Doel" },
  "Revenue": { en: "Revenue", nl: "Inkomsten" },
  "Occupancy": { en: "Occupancy", nl: "Bezetting" },
  "Open rent": { en: "Open rent", nl: "Openstaande huur" },
  "Review rent aging": { en: "Review rent aging", nl: "Bekijk huurachterstanden" },
  "Review units": { en: "Review units", nl: "Bekijk eenheden" },
  "Handled this week": { en: "Handled this week", nl: "Deze week verwerkt" },
  "View autonomous ledger": { en: "View autonomous ledger", nl: "Bekijk autonoom logboek" },
  "Ticket Details": { en: "Ticket Details", nl: "Ticketdetails" },
  "Dispatch": { en: "Dispatch", nl: "Verzenden" },
  "Reply": { en: "Reply", nl: "Beantwoorden" },
  "Replied": { en: "Replied", nl: "Beantwoord" },
  "Send nudge": { en: "Send nudge", nl: "Herinnering sturen" },
  "Nudged": { en: "Nudged", nl: "Herinnering gestuurd" },
  "Review": { en: "Review", nl: "Beoordelen" },
  "Monthly Rent": { en: "Monthly Rent", nl: "Maandelijkse Huur" },
  "Security Deposit": { en: "Security Deposit", nl: "Waarborgsom" },
  "Lease Commencement": { en: "Lease Commencement", nl: "Ingangsdatum Huur" },
  "Lease Expiry": { en: "Lease Expiry", nl: "Einddatum Huur" },
  "Identity & Vetting": { en: "Identity & Vetting", nl: "Identiteit & Screening" },
  "iDIN Verified": { en: "iDIN Verified", nl: "iDIN Geverifieerd" },
  "Payment Status": { en: "Payment Status", nl: "Betalingsstatus" },
  "Rent up to date": { en: "Rent up to date", nl: "Huur bijgewerkt" },
  "Invoice Reference": { en: "Invoice Reference", nl: "Factuurreferentie" },
  "Tenant & Unit": { en: "Tenant & Unit", nl: "Huurder & Eenheid" },
  "Contract Rent": { en: "Contract Rent", nl: "Contracthuur" },
  "Settlement / Due Date": { en: "Settlement / Due Date", nl: "Voldaan / Vervaldatum" },
  "Payment Channel": { en: "Payment Channel", nl: "Betaalkanaal" },
  "PAID": { en: "PAID", nl: "BETAALD" },
  "Due": { en: "Due", nl: "Vervalt" },
  "portfolio units": { en: "portfolio units", nl: "eenheden in portefeuille" },
  "collected on time": { en: "collected on time", nl: "op tijd geïncasseerd" },
  "in arrears": { en: "in arrears", nl: "met achterstand" },
  "leased units": { en: "leased units", nl: "verhuurde eenheden" },
  "tenant": { en: "tenant", nl: "huurder" },
  "tenants": { en: "tenants", nl: "huurders" },
  "Selected": { en: "Selected", nl: "Geselecteerd" },
  "occupied": { en: "occupied", nl: "bezet" },
  "Export CSV": { en: "Export CSV", nl: "CSV Exporteren" },
  "Export Rent Roll to CSV": { en: "Export Rent Roll to CSV", nl: "Huurdersoverzicht naar CSV exporteren" },
  "Portfolio Occupancy Rate (%)": { en: "Portfolio Occupancy Rate (%)", nl: "Portefeuille Bezettingsgraad (%)" },
  "Occupancy Rate (%)": { en: "Occupancy Rate (%)", nl: "Bezettingsgraad (%)" },
  "Monthly Rent Revenue & Collection Trend (Last 6 Months)": {
    en: "Monthly Rent Revenue & Collection Trend (Last 6 Months)",
    nl: "Maandelijkse Huurinkomsten & Incassotrend (Laatste 6 Maanden)"
  },
  "Portfolio Occupancy Progression (Last 6 Months)": {
    en: "Portfolio Occupancy Progression (Last 6 Months)",
    nl: "Portefeuille Bezettingsontwikkeling (Laatste 6 Maanden)"
  },
  "Comparing scheduled lease commitments against collected receipts. Click a bar to filter ledger.": {
    en: "Comparing scheduled lease commitments against collected receipts. Click a bar to filter ledger.",
    nl: "Vergelijking van geplande huurverplichtingen met ontvangen betalingen. Klik op een punt om te filteren."
  },
  "Tracking occupied residential units over time (growing from 94.5% to 100.0%).": {
    en: "Tracking occupied residential units over time (growing from 94.5% to 100.0%).",
    nl: "Bezettingsgraad van woonruimten in de tijd (gegroeid van 94,5% naar 100,0%)."
  },
  "Click node to select cycle": {
    en: "Click node to select cycle",
    nl: "Klik op punt om periode te selecteren"
  },

  // Search Placeholders
  "Search tickets...": { en: "Search tickets...", nl: "Tickets zoeken..." },
  "Search transactions...": { en: "Search transactions...", nl: "Transacties zoeken..." },
  "Search tenants...": { en: "Search tenants...", nl: "Huurders zoeken..." },
  "Search properties...": { en: "Search properties...", nl: "Panden zoeken..." },
  "Search messages...": { en: "Search messages...", nl: "Berichten zoeken..." },
  "Search contacts...": { en: "Search contacts...", nl: "Contacten zoeken..." },
  "Search tenant, unit, invoice...": { en: "Search tenant, unit, invoice...", nl: "Zoek huurder, eenheid, factuur..." },
  "Search...": { en: "Search...", nl: "Zoeken..." },

  // Common Action Buttons & Labels
  "New ticket": { en: "New ticket", nl: "Nieuw ticket" },
  "New Ticket": { en: "New Ticket", nl: "Nieuw ticket" },
  "Add Tenant": { en: "Add Tenant", nl: "Huurder toevoegen" },
  "Add Property": { en: "Add Property", nl: "Pand toevoegen" },
  "Download Export": { en: "Download Export", nl: "Export downloaden" },
  "Export": { en: "Export", nl: "Exporteren" },
  "Filter": { en: "Filter", nl: "Filteren" },
  "Approve": { en: "Approve", nl: "Goedkeuren" },
  "Reject": { en: "Reject", nl: "Afwijzen" },
  "Approve & Dispatch": { en: "Approve & Dispatch", nl: "Goedkeuren & Verzenden" },
  "Edit": { en: "Edit", nl: "Bewerken" },
  "History": { en: "History", nl: "Geschiedenis" },
  "Save": { en: "Save", nl: "Opslaan" },
  "Cancel": { en: "Cancel", nl: "Annuleren" },
  "Close": { en: "Close", nl: "Sluiten" },
  "Retry": { en: "Retry", nl: "Opnieuw" },
  "Retry Draft": { en: "Retry Draft", nl: "Concept opnieuw maken" },
  "Open in Inbox": { en: "Open in Inbox", nl: "Openen in Inbox" },
  "View Details": { en: "View Details", nl: "Details bekijken" },
  "Send": { en: "Send", nl: "Verzenden" },
  "Send approval": { en: "Send approval", nl: "Goedkeuring verzenden" },
  "Open technician": { en: "Open technician", nl: "Monteur openen" },
  "Review dispatch": { en: "Review dispatch", nl: "Verzending bekijken" },

  // Status & Urgency Labels
  "urgent": { en: "urgent", nl: "dringend" },
  "Urgent": { en: "Urgent", nl: "Dringend" },
  "emergency": { en: "emergency", nl: "noodgeval" },
  "Emergency": { en: "Emergency", nl: "Noodgeval" },
  "in progress": { en: "in progress", nl: "in behandeling" },
  "In Progress": { en: "In Progress", nl: "In behandeling" },
  "open": { en: "open", nl: "open" },
  "high": { en: "high", nl: "hoog" },
  "medium": { en: "medium", nl: "gemiddeld" },
  "low": { en: "low", nl: "laag" },
  "pending": { en: "pending", nl: "in afwachting" },
  "completed": { en: "completed", nl: "voltooid" },
  "resolved": { en: "resolved", nl: "opgelost" },
  "overdue": { en: "overdue", nl: "achterstallig" },
  "Status": { en: "Status", nl: "Status" },
  "Status:": { en: "Status:", nl: "Status:" },
  "Status: pending": { en: "Status: pending", nl: "Status: in afwachting" },
  "NOTICE": { en: "NOTICE", nl: "KENNISGEVING" },
  "TICKET": { en: "TICKET", nl: "TICKET" },
  "Needs you": { en: "Needs you", nl: "Vereist actie" },
  "Waiting on others": { en: "Waiting on others", nl: "Wachten op anderen" },
  "New leads": { en: "New leads", nl: "Nieuwe leads" },
  "Open Inbox →": { en: "Open Inbox →", nl: "Open Inbox →" },
  "Open all →": { en: "Open all →", nl: "Alles openen →" },
  "Filters": { en: "Filters", nl: "Filters" },
  "Reset all": { en: "Reset all", nl: "Alles herstellen" },
  "Clear search": { en: "Clear search", nl: "Zoekopdracht wissen" },
  "Date": { en: "Date", nl: "Datum" },
  "Amount": { en: "Amount", nl: "Bedrag" },
  "Counterparty": { en: "Counterparty", nl: "Tegenpartij" },
  "Unit": { en: "Unit", nl: "Eenheid" },
  "Reference": { en: "Reference", nl: "Referentie" },
  "PO Cap": { en: "PO Cap", nl: "Inkooporderlimiet" },
  "Contractor / Technician": { en: "Contractor / Technician", nl: "Aannemer / Monteur" },
  "Tenant": { en: "Tenant", nl: "Huurder" },
  "Category": { en: "Category", nl: "Categorie" },
  "Reported": { en: "Reported", nl: "Gemeld" },
  "Notes": { en: "Notes", nl: "Notities" },

  // Dashboard specifics
  "Today's Focus": { en: "Today's Focus", nl: "Focus van Vandaag" },
  "Triage Queue": { en: "Triage Queue", nl: "Wachtrij Triage" },
  "All clear. No urgent tasks requiring your attention.": {
    en: "All clear. No urgent tasks requiring your attention.",
    nl: "Alles bijgewerkt. Geen urgente taken die uw aandacht vereisen.",
  },
  "Recent Activity": { en: "Recent Activity", nl: "Recente Activiteit" },

  // Super Agent UI
  "agent.panel_title": { en: "Super Agent", nl: "Super Agent" },
  "agent.welcome_sub": {
    en: "I know your queue, portfolio, and financial logs. Ask me to explain an item, find a document, check tenant arrears, or pick what to do first.",
    nl: "Ik beheer uw wachtrij, portfolio en financiën. Vraag me om een item toe te lichten, een document te zoeken, huurachterstanden te controleren of te bepalen wat als eerste moet gebeuren.",
  },
  "agent.ask_placeholder": {
    en: "Ask Super Agent across portfolio, maintenance, arrears...",
    nl: "Vraag Super Agent over portfolio, onderhoud, achterstanden...",
  },
  "agent.listening_en": { en: "Listening (English)...", nl: "Luisteren (Engels)..." },
  "agent.listening_nl": { en: "Listening (Dutch)...", nl: "Luisteren (Nederlands)..." },
  "What should I do first?": { en: "What should I do first?", nl: "Wat moet ik eerst doen?" },
  "What should I do first? →": { en: "What should I do first? →", nl: "Wat moet ik eerst doen? →" },
  "Show me today's task": { en: "Show me today's task", nl: "Toon mijn taak van vandaag" },
  "Show me today's tasks": { en: "Show me today's tasks", nl: "Toon mijn taken van vandaag" },
  "Draft Generation Notice": { en: "Draft Generation Notice", nl: "Kennisgeving Conceptaanmaak" },
  "EstateOS could not draft a reply for a new message on this case. Please look at it yourself.": {
    en: "EstateOS could not draft a reply for a new message on this case. Please look at it yourself.",
    nl: "EstateOS kon geen antwoord opstellen voor een nieuw bericht in dit dossier. Bekijk het zelf.",
  },
};

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  toggleLanguage: () => void;
  t: (key: string, fallback?: string) => string;
}

const LanguageContext = createContext<LanguageContextType>({
  language: "en",
  setLanguage: () => {},
  toggleLanguage: () => {},
  t: (key: string, fallback?: string) => fallback || key,
});

const STORAGE_KEY = "estateos_user_language";

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>("en");
  const [isInitialized, setIsInitialized] = useState<boolean>(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "nl" || stored === "en") {
        setLanguageState(stored);
      }
    } catch {
      // LocalStorage unavailable
    }
    setIsInitialized(true);
  }, []);

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // Ignore
    }
  };

  const toggleLanguage = () => {
    const nextLang = language === "en" ? "nl" : "en";
    setLanguage(nextLang);
  };

  const t = (key: string, fallback?: string): string => {
    if (!key) return "";
    const direct = DICTIONARY[key] || DICTIONARY[key.trim()];
    if (direct && direct[language]) {
      return direct[language];
    }
    // Case-insensitive fallback
    const lowerKey = key.trim().toLowerCase();
    for (const [k, val] of Object.entries(DICTIONARY)) {
      if (k.toLowerCase() === lowerKey && val[language]) {
        return val[language];
      }
    }
    return fallback !== undefined ? fallback : key;
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, toggleLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  return useContext(LanguageContext);
}
