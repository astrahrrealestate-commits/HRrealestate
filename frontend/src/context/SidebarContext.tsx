"use client";

import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { useSuperAgent } from "@/context/SuperAgentContext";

interface SidebarContextType {
  isCollapsed: boolean;
  setIsCollapsed: (collapsed: boolean | ((prev: boolean) => boolean)) => void;
  toggleSidebar: () => void;
  expandSidebar: () => void;
  collapseSidebar: () => void;
  sidebarWidth: number;
  setSidebarWidth: (width: number) => void;
  resetSidebarWidth: () => void;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

const STORAGE_KEY = "estateos_sidebar_collapsed";
const WIDTH_STORAGE_KEY = "estateos_sidebar_width";
const DEFAULT_SIDEBAR_WIDTH = 240;
const MIN_SIDEBAR_WIDTH = 180;
const MAX_SIDEBAR_WIDTH = 320;

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const { isOpen: isSuperAgentOpen } = useSuperAgent();

  // Start with expanded (false) by default
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [sidebarWidth, setSidebarWidthState] = useState<number>(DEFAULT_SIDEBAR_WIDTH);
  const isSuperAgentOpenRef = useRef(isSuperAgentOpen);

  // Initialize preference from localStorage on client mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setIsCollapsed(stored === "true");
      }
      const storedW = localStorage.getItem(WIDTH_STORAGE_KEY);
      if (storedW !== null) {
        const parsed = Number(storedW);
        if (!Number.isNaN(parsed) && parsed >= MIN_SIDEBAR_WIDTH && parsed <= MAX_SIDEBAR_WIDTH) {
          setSidebarWidthState(parsed);
        }
      }
    } catch {
      // LocalStorage might be unavailable in private browsing
    }
  }, []);

  const setSidebarWidth = (width: number) => {
    const clamped = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, Math.round(width)));
    setSidebarWidthState(clamped);
    try {
      localStorage.setItem(WIDTH_STORAGE_KEY, String(clamped));
    } catch {}
  };

  const resetSidebarWidth = () => {
    setSidebarWidthState(DEFAULT_SIDEBAR_WIDTH);
    try {
      localStorage.setItem(WIDTH_STORAGE_KEY, String(DEFAULT_SIDEBAR_WIDTH));
    } catch {}
  };

  // When SuperAgent opens, auto-minimize to give room, but allow user to expand anytime
  useEffect(() => {
    if (!isSuperAgentOpenRef.current && isSuperAgentOpen) {
      // SuperAgent opened: auto-collapse
      setIsCollapsed(true);
    } else if (isSuperAgentOpenRef.current && !isSuperAgentOpen) {
      // SuperAgent closed: restore saved preference if present
      try {
        const stored = localStorage.getItem(STORAGE_KEY);
        setIsCollapsed(stored === "true");
      } catch {
        setIsCollapsed(false);
      }
    }
    isSuperAgentOpenRef.current = isSuperAgentOpen;
  }, [isSuperAgentOpen]);

  const toggleSidebar = () => {
    setIsCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
      } catch {}
      return next;
    });
  };

  const expandSidebar = () => {
    setIsCollapsed(false);
    try {
      localStorage.setItem(STORAGE_KEY, "false");
    } catch {}
  };

  const collapseSidebar = () => {
    setIsCollapsed(true);
    try {
      localStorage.setItem(STORAGE_KEY, "true");
    } catch {}
  };

  // Keyboard shortcut Ctrl+B or Cmd+B to toggle sidebar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        const target = e.target as HTMLElement | null;
        if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
          return;
        }
        e.preventDefault();
        toggleSidebar();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <SidebarContext.Provider
      value={{
        isCollapsed,
        setIsCollapsed,
        toggleSidebar,
        expandSidebar,
        collapseSidebar,
        sidebarWidth,
        setSidebarWidth,
        resetSidebarWidth,
      }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

export function useSidebar() {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error("useSidebar must be used within a SidebarProvider");
  }
  return context;
}

