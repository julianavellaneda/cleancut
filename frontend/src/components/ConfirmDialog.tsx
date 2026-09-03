"use client";

import { useCallback, useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The themed replacement for `window.confirm` on the admin screen.
 *
 * `window.confirm` was doing real safety work - it is the only thing standing
 * between a click and an irreversible wipe - so replacing it with a styled div
 * has to keep every property that made it safe, not just its shape:
 *
 *   - Focus lands on the **cancel** button, so a stray Return keeps the data.
 *   - Escape cancels, and so does a click on the backdrop. Both resolve toward
 *     keeping everything; there is no gesture that confirms by accident.
 *   - Tab is trapped inside the dialog, so the buttons behind it cannot be
 *     reached while it is open - a browser dialog is modal to the whole page
 *     and this has to be modal to the same degree.
 *   - Focus returns to whatever opened it on close.
 *
 * The cancel button is worded as what it *does* ("Keep everything") rather than
 * as "Cancel". A reader skimming two buttons under a red circle should be able
 * to pick the safe one from its label alone.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = "Keep everything",
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    // Read before focus moves, so this is the element that opened the dialog
    // rather than one of our own buttons.
    const opener = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;

      const panel = panelRef.current;
      if (!panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;

      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      // jsdom and a real browser agree on the wrap; what they do *not* agree on
      // is the default, so both ends are handled explicitly rather than relying
      // on the browser walking off the end of the panel.
      if (event.shiftKey && (active === first || !panel.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    },
    [onCancel]
  );

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-backdrop p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
      onKeyDown={onKeyDown}
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-body"
        className="flex w-[min(440px,100%)] flex-col gap-3.5 rounded-2xl bg-surface p-6.5 pb-5.5 shadow-lg"
      >
        <div
          aria-hidden
          className="grid size-11 place-items-center rounded-full bg-danger-100 font-heading text-[22px] text-danger-700"
        >
          !
        </div>
        <h2 id="confirm-dialog-title" className="m-0 font-heading text-[22px]">
          {title}
        </h2>
        <p id="confirm-dialog-body" className="m-0 text-sm text-muted text-pretty">
          {body}
        </p>
        <div className="mt-1.5 flex justify-end gap-2.5">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-full border border-divider px-4.5 py-2.5 text-sm transition-colors hover:bg-surface2"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-full bg-danger px-5 py-2.5 font-heading text-sm text-onacc transition-opacity hover:opacity-90"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmDialog;
