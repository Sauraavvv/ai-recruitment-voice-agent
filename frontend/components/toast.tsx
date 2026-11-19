"use client";

import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
type Notify = (kind: Toast["kind"], text: string) => void;

const ToastContext = createContext<Notify>(() => undefined);

/** Short messages after an action, bottom right, gone after 5 s. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const notify = useCallback<Notify>((kind, text) => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all.slice(-3), { id, kind, text }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 5000);
  }, []);
  const tone = {
    success: "border-green-500/30 text-green-200",
    error: "border-red-500/30 text-red-200",
    info: "border-white/10 text-zinc-200",
  };
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-2"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto rounded-xl border bg-[#202226] px-4 py-3 text-sm shadow-lg ${tone[t.kind]}`}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
