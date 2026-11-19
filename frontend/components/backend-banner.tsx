"use client";

import { useEffect, useState } from "react";

const CHECK_MS = 15_000;

/** A banner while the backend can't be reached (checked every 15 s, and when back online). */
export function BackendBanner() {
  const [down, setDown] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const response = await fetch("/health", { cache: "no-store" });
        if (!cancelled) setDown(!response.ok);
      } catch {
        if (!cancelled) setDown(true);
      }
    };
    void check();
    const timer = setInterval(check, CHECK_MS);
    window.addEventListener("online", check);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener("online", check);
    };
  }, []);
  if (!down) return null;
  return (
    <div
      role="alert"
      className="mb-4 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
    >
      The HireCall server can&apos;t be reached. Data on this page may be out of date; it will
      refresh when the connection is back.
    </div>
  );
}
