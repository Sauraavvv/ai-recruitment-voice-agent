"use client";

import { useEffect, useRef } from "react";

function isModal(dialog: HTMLDialogElement): boolean {
  try {
    return dialog.matches(":modal");
  } catch {
    return dialog.open; // a browser (or test DOM) without :modal
  }
}

/**
 * A native <dialog> shown as a modal (top layer, blurred backdrop, page behind inert) while
 * `open`; `onClose` runs when it closes (Esc, `dialog.close()`). If the browser ever leaves it
 * open but not modal (seen once after coming back to the page: no backdrop, the page behind
 * usable), it is shown as a modal again, keeping its content: checked on every change and
 * whenever the page becomes visible again. Put the returned ref on the <dialog>.
 */
export function useModal(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDialogElement>(null);
  const handler = useRef(onClose);
  useEffect(() => {
    handler.current = onClose;
  });

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    let reshowing = 0;
    const onCloseEvent = () => {
      if (reshowing > 0) {
        reshowing -= 1; // our own close() before showing it again: not a real close
        return;
      }
      handler.current();
    };
    const sync = () => {
      if (!open) {
        if (dialog.open) dialog.close?.();
        return;
      }
      if (isModal(dialog)) return;
      if (dialog.open) {
        reshowing += 1;
        dialog.close();
      }
      dialog.showModal?.();
    };
    const onVisible = () => {
      if (!document.hidden) sync();
    };
    dialog.addEventListener("close", onCloseEvent);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", sync);
    window.addEventListener("focus", sync);
    sync();
    return () => {
      dialog.removeEventListener("close", onCloseEvent);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", sync);
      window.removeEventListener("focus", sync);
    };
  }, [open]);

  return ref;
}
