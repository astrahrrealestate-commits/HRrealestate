"use client";

import { useEffect, useRef } from "react";

interface PollingOptions {
  /** A new key runs `tick` at once (e.g. the filter changed). */
  restartKey?: string;
  /** False pauses polling entirely, e.g. when the profile may not open the section. Default true. */
  enabled?: boolean;
}

/** Runs `tick` now and then every `intervalMs`, but only while the tab is visible; it runs again as soon as the tab
 * comes back. `tick` may change between renders without restarting the timer. */
export function usePolling(
  tick: () => void | Promise<void>,
  intervalMs: number,
  { restartKey, enabled = true }: PollingOptions = {}
): void {
  const latest = useRef(tick);
  const inFlight = useRef(false);
  useEffect(() => {
    latest.current = tick;
  });

  useEffect(() => {
    if (!enabled) return;
    const run = () => {
      if (document.hidden || inFlight.current) return;
      inFlight.current = true;
      void Promise.resolve(latest.current()).finally(() => {
        inFlight.current = false;
      });
    };
    run();
    const timer = setInterval(run, intervalMs);
    document.addEventListener("visibilitychange", run);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [intervalMs, restartKey, enabled]);
}
