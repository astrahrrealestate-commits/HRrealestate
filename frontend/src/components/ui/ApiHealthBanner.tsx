"use client";

import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";
import { onApiHealthChange, probeApiHealth } from "@/lib/backend";
import { useLanguage } from "@/context/LanguageContext";

/**
 * One fixed banner for the whole dashboard: visible while the API is unreachable or answering 5xx, gone on the next
 * successful call. Pages keep their graceful fallbacks; this makes the failure visible instead of silent.
 */
export function ApiHealthBanner() {
  const { language } = useLanguage();
  const [healthy, setHealthy] = useState(true);

  useEffect(() => {
    const unsub = onApiHealthChange(setHealthy);
    let wakeTimer: ReturnType<typeof setTimeout> | null = null;
    const verifySoon = () => {
      if (wakeTimer !== null) clearTimeout(wakeTimer);
      wakeTimer = setTimeout(() => {
        wakeTimer = null;
        void probeApiHealth();
      }, 500);
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") verifySoon();
    };
    window.addEventListener("online", verifySoon);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      unsub();
      if (wakeTimer !== null) clearTimeout(wakeTimer);
      window.removeEventListener("online", verifySoon);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  if (healthy) return null;

  return (
    <div
      role="alert"
      className="fixed top-0 inset-x-0 z-[200] flex items-center justify-center gap-2 bg-amber-500 text-black text-[12.5px] font-medium px-4 py-1.5 shadow-md"
    >
      <WifiOff className="w-3.5 h-3.5 shrink-0" />
      <span>
        {language === "nl"
          ? "Geen verbinding met de EstateOS-server — u ziet de laatst bekende gegevens."
          : "No connection to the EstateOS server — showing the last known data."}
      </span>
    </div>
  );
}
