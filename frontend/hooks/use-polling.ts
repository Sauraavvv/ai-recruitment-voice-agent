"use client";

import { useEffect, useRef } from "react";

export const FAST_POLL_MS = 3_000; // a call is active somewhere on the page
export const SLOW_POLL_MS = 30_000;

/**
 * Calls `refresh` every 3 s while `active` (a visible call is live) and every 30 s otherwise.
 * Paused while the tab is hidden; refreshes at once when it becomes visible again.
 * (phase-08 P8-T9: status changes appear within 5 s of the webhook.)
 */
export function usePolling(refresh: () => void, active: boolean, enabled = true) {
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  });

  useEffect(() => {
    if (!enabled) return;
    const interval = active ? FAST_POLL_MS : SLOW_POLL_MS;
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      stop();
      timer = setInterval(() => refreshRef.current(), interval);
    };
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        refreshRef.current();
        start();
      }
    };
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [active, enabled]);
}
