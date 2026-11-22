import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useModal } from "@/hooks/use-modal";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// jsdom has no top layer: a dialog is "modal" when showModal() opened it
let modal = new WeakSet<HTMLDialogElement>();

beforeEach(() => {
  modal = new WeakSet();
  const proto = HTMLDialogElement.prototype;
  proto.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
    modal.add(this);
  });
  proto.close = vi.fn(function (this: HTMLDialogElement) {
    if (!this.hasAttribute("open")) return;
    this.removeAttribute("open");
    modal.delete(this);
    this.dispatchEvent(new Event("close"));
  });
  const matches = Element.prototype.matches;
  vi.spyOn(Element.prototype, "matches").mockImplementation(function (
    this: Element,
    selector: string,
  ) {
    if (selector === ":modal") return modal.has(this as HTMLDialogElement);
    return matches.call(this, selector);
  });
});

function Dialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useModal(open, onClose);
  return <dialog ref={ref} aria-label="test" />;
}

describe("useModal", () => {
  it("opens as a modal and closes", () => {
    const onClose = vi.fn();
    const { rerender, getByRole } = render(<Dialog open onClose={onClose} />);
    const dialog = getByRole("dialog", { hidden: true }) as HTMLDialogElement;
    expect(modal.has(dialog)).toBe(true);
    rerender(<Dialog open={false} onClose={onClose} />);
    expect(dialog.open).toBe(false);
  });

  it("shows it as a modal again when the browser left it open but not modal", () => {
    const onClose = vi.fn();
    const { getByRole } = render(<Dialog open onClose={onClose} />);
    const dialog = getByRole("dialog", { hidden: true }) as HTMLDialogElement;
    modal.delete(dialog); // still open, no longer modal (no backdrop, page usable)
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(modal.has(dialog)).toBe(true);
    expect(onClose).not.toHaveBeenCalled(); // the reopening isn't a close
  });

  it("passes on a real close (Esc)", () => {
    const onClose = vi.fn();
    const { getByRole } = render(<Dialog open onClose={onClose} />);
    const dialog = getByRole("dialog", { hidden: true }) as HTMLDialogElement;
    act(() => dialog.close());
    expect(onClose).toHaveBeenCalledOnce();
  });
});
