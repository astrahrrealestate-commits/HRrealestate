"use client";

import { useEffect, useRef } from "react";

/** Runs `tick` now and then every `intervalMs`, but only while the tab is visible; it runs again as soon as the tab
 * comes back. `tick` may change between renders without restarting the timer. A new `restartKey` runs it at once. */
export function usePolling(tick: () => void | Promise<void>, intervalMs: number, restartKey?: string): void {
  const latest = useRef(tick);
  useEffect(() => {
    latest.current = tick;
  });

  useEffect(() => {
    const run = () => {
      if (!document.hidden) void latest.current();
    };
    run();
    const timer = setInterval(run, intervalMs);
    document.addEventListener("visibilitychange", run);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [intervalMs, restartKey]);
}
