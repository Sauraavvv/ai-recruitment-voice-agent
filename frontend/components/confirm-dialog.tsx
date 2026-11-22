"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/ui";
import { useModal } from "@/hooks/use-modal";

/** Modal confirmation (native <dialog>: focus trap, Esc to close). */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useModal(open, onClose);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      aria-labelledby="confirm-title"
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-3xl border border-white/10 bg-[#18191c] p-0 text-white backdrop:bg-black/70"
    >
      {open && (
        <div className="p-6">
          <h2 id="confirm-title" className="font-display text-lg font-semibold">
            {title}
          </h2>
          {children && <div className="mt-3 text-sm text-zinc-300">{children}</div>}
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose} disabled={busy}>
              {cancelLabel}
            </Button>
            <Button
              variant={danger ? "danger" : "primary"}
              onClick={onConfirm}
              disabled={busy || confirmDisabled}
              autoFocus
            >
              {busy ? "Working…" : confirmLabel}
            </Button>
          </div>
        </div>
      )}
    </dialog>
  );
}
