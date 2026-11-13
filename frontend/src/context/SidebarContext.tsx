"use client";

import React, { createContext, useContext, useState, useEffect, useRef } from "react";
import { useSuperAgent } from "@/context/SuperAgentContext";

interface SidebarContextType {
  isCollapsed: boolean;
  setIsCollapsed: (collapsed: boolean | ((prev: boolean) => boolean)) => void;
  toggleSidebar: () => void;
  expandSidebar: () => void;
  collapseSidebar: () => void;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

const STORAGE_KEY = "estateos_sidebar_collapsed";

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const { isOpen: isSuperAgentOpen } = useSuperAgent();

  // Start with expanded (false) by default
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const isSuperAgentOpenRef = useRef(isSuperAgentOpen);

  // Initialize preference from localStorage on client mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored !== null) {
        setIsCollapsed(stored === "true");
      }
    } catch {
      // LocalStorage might be unavailable in private browsing
    }
  }, []);

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

