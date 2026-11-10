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

  // Common Actions & Badges
  "common.approve": { en: "Approve", nl: "Goedkeuren" },
  "common.reject": { en: "Reject", nl: "Afwijzen" },
  "common.retry": { en: "Retry", nl: "Opnieuw" },
  "common.open_in_inbox": { en: "Open in Inbox", nl: "Openen in Inbox" },
  "common.view_details": { en: "View Details", nl: "Details bekijken" },
  "common.cancel": { en: "Cancel", nl: "Annuleren" },
  "common.save": { en: "Save", nl: "Opslaan" },
  "common.filter": { en: "Filter", nl: "Filteren" },
  "common.all": { en: "All", nl: "Alles" },
  "common.search": { en: "Search", nl: "Zoeken" },
  "common.loading": { en: "Loading...", nl: "Laden..." },
  "common.status": { en: "Status", nl: "Status" },
  "common.pending": { en: "Pending", nl: "In afwachting" },
  "common.completed": { en: "Completed", nl: "Voltooid" },
  "common.urgent": { en: "Urgent", nl: "Urgent" },
  "common.emergency": { en: "Emergency", nl: "Noodgeval" },
  "common.high": { en: "High", nl: "Hoog" },
  "common.medium": { en: "Medium", nl: "Gemiddeld" },
  "common.low": { en: "Low", nl: "Laag" },
  "common.notice": { en: "NOTICE", nl: "KENNISGEVING" },

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
  "agent.what_should_i_do": { en: "What should I do first? →", nl: "Wat moet ik eerst doen? →" },
  "agent.show_todays_tasks": { en: "Show me today's tasks", nl: "Toon taken van vandaag" },
  "agent.send_approval": { en: "Send approval", nl: "Goedkeuring verzenden" },
  "agent.open_technician": { en: "Open technician", nl: "Monteur openen" },
  "agent.review_dispatch": { en: "Review dispatch", nl: "Verzending bekijken" },
  "agent.retry_draft": { en: "Retry Draft", nl: "Concept opnieuw" },

  // Direct Button & Badge Strings (matches actions directly)
  "What should I do first?": { en: "What should I do first?", nl: "Wat moet ik eerst doen?" },
  "What should I do first? →": { en: "What should I do first? →", nl: "Wat moet ik eerst doen? →" },
  "Show me today's task": { en: "Show me today's task", nl: "Toon mijn taak van vandaag" },
  "Show me today's tasks": { en: "Show me today's tasks", nl: "Toon mijn taken van vandaag" },
  "Send approval": { en: "Send approval", nl: "Goedkeuring verzenden" },
  "Open technician": { en: "Open technician", nl: "Monteur openen" },
  "Review dispatch": { en: "Review dispatch", nl: "Verzending bekijken" },
  "Retry Draft": { en: "Retry Draft", nl: "Concept opnieuw maken" },
  "Open in Inbox": { en: "Open in Inbox", nl: "Openen in Inbox" },
  "Draft Generation Notice": { en: "Draft Generation Notice", nl: "Kennisgeving Conceptaanmaak" },
  "EstateOS could not draft a reply for a new message on this case. Please look at it yourself.": {
    en: "EstateOS could not draft a reply for a new message on this case. Please look at it yourself.",
    nl: "EstateOS kon geen antwoord opstellen voor een nieuw bericht in dit dossier. Bekijk het zelf.",
  },
  "Status: pending": { en: "Status: pending", nl: "Status: in afwachting" },
  "pending": { en: "pending", nl: "in afwachting" },
  "Approved": { en: "Approved", nl: "Goedgekeurd" },
  "Pending": { en: "Pending", nl: "In afwachting" },
  "NOTICE": { en: "NOTICE", nl: "KENNISGEVING" },
  "URGENT": { en: "URGENT", nl: "URGENT" },
  "TICKET": { en: "TICKET", nl: "TICKET" },

  // Maintenance & Pages
  "maintenance.title": { en: "Maintenance", nl: "Onderhoud" },
  "maintenance.open_cases": { en: "Open Cases", nl: "Openstaande dossiers" },
  "maintenance.technician": { en: "Contractor / Technician", nl: "Aannemer / Monteur" },
  "tenants.title": { en: "Tenants", nl: "Huurders" },
  "properties.title": { en: "Properties", nl: "Panden" },
  "inbox.title": { en: "Inbox & Messages", nl: "Inbox & Berichten" },
  "money.title": { en: "Financial Control", nl: "Financieel Overzicht" },
  "contacts.title": { en: "Contacts Directory", nl: "Contactpersonen" },
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
    const item = DICTIONARY[key];
    if (item && item[language]) {
      return item[language];
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
