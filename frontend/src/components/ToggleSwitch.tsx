"use client";

import { useId } from "react";

import { cn } from "@/lib/utils";

/**
 * The mockup's toggle: a title, a sentence saying what it actually does, and a
 * sliding track, all inside one large click target.
 *
 * It replaces an `<input type="checkbox">`, so the accessible half is the part
 * that matters. `role="switch"` with `aria-checked` is the honest role for a
 * control with no form value, and `aria-labelledby` points at the *title*
 * alone: without it the accessible name would swallow the description too, and
 * `getByLabelText("Auto-apply markers")` - the query the upload tests are built
 * on - would no longer find it. The description is attached with
 * `aria-describedby`, which is where a sentence of explanation belongs.
 */
export function ToggleSwitch({
  checked,
  onChange,
  title,
  description,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  title: string;
  description: string;
  disabled?: boolean;
}) {
  const titleId = useId();
  const descriptionId = useId();

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "flex w-full items-start gap-3 rounded-[22px] border border-divider p-3.5 text-left transition-colors",
        "hover:border-acc disabled:pointer-events-none disabled:opacity-50",
        checked ? "bg-acc-100" : "bg-transparent"
      )}
    >
      <span
        aria-hidden
        className={cn(
          "relative mt-0.5 h-5 w-[34px] flex-none rounded-full transition-colors",
          checked ? "bg-acc" : "bg-surface2"
        )}
      >
        <span
          className={cn(
            "absolute top-[3px] size-3.5 rounded-full bg-bg transition-[left]",
            checked ? "left-4" : "left-[3px]"
          )}
        />
      </span>
      <span className="min-w-0">
        <span id={titleId} className="block text-sm font-semibold">
          {title}
        </span>
        <span id={descriptionId} className="block text-xs text-muted text-pretty">
          {description}
        </span>
      </span>
    </button>
  );
}
