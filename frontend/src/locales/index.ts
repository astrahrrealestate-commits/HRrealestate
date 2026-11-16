import { commonTranslations } from "./common";
import { inboxTranslations } from "./inbox";
import { propertiesTranslations } from "./properties";
import { tenantsTranslations } from "./tenants";
import { contactsTranslations } from "./contacts";
import { maintenanceTranslations } from "./maintenance";
import { moneyTranslations } from "./money";
import { reportsTranslations } from "./reports";
import { settingsTranslations } from "./settings";
import { knowledgeTranslations } from "./knowledge";
import { adminTranslations } from "./admin";
import { assistantTranslations } from "./assistant";

export const ALL_DICTIONARY: Record<string, { en: string; nl: string }> = {
  ...commonTranslations,
  ...inboxTranslations,
  ...propertiesTranslations,
  ...tenantsTranslations,
  ...contactsTranslations,
  ...maintenanceTranslations,
  ...moneyTranslations,
  ...reportsTranslations,
  ...settingsTranslations,
  ...knowledgeTranslations,
  ...adminTranslations,
  ...assistantTranslations,
};
