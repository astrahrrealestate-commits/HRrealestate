"use client";

import { useState, useEffect, useCallback } from "react";

const SIDEBAR_STORAGE_KEY = "estateos_sidebar_collapsed";
const SIDEBAR_TOGGLE_EVENT = "estateos-sidebar-toggle";

export function useSidebarState() {
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [isHydrated, setIsHydrated] = useState<boolean>(false);

  // Initialize from localStorage on mount (prevents SSR hydration mismatch)
  useEffect(() => {
    try {
      const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
      if (stored !== null) {
        setIsCollapsed(stored === "true");
      }
    } catch {
      // Fallback if localStorage is disabled or unavailable
    }
    setIsHydrated(true);

    const handleStorageChange = () => {
      try {
        const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
        if (stored !== null) {
          setIsCollapsed(stored === "true");
        }
      } catch {}
    };

    window.addEventListener(SIDEBAR_TOGGLE_EVENT, handleStorageChange);
    window.addEventListener("storage", handleStorageChange);

    return () => {
      window.removeEventListener(SIDEBAR_TOGGLE_EVENT, handleStorageChange);
      window.removeEventListener("storage", handleStorageChange);
    };
  }, []);

  const toggleSidebar = useCallback(() => {
    setIsCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      } catch {}
      window.dispatchEvent(new Event(SIDEBAR_TOGGLE_EVENT));
      return next;
    });
  }, []);

  // Keyboard shortcut: Ctrl+B or Cmd+B
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        const target = e.target as HTMLElement;
        if (
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.isContentEditable)
        ) {
          return;
        }
        e.preventDefault();
        toggleSidebar();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [toggleSidebar]);

  return {
    isCollapsed: isHydrated ? isCollapsed : false,
    toggleSidebar,
    isHydrated,
  };
}

