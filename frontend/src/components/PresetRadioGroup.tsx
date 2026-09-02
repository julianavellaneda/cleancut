"use client";

import { useId, useRef } from "react";

import { Preset } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The rule preset picker: the `<select>` rebuilt as the mockup's column of
 * pills with a custom radio dot.
 *
 * Built as a real `radiogroup` rather than styled `<div>`s, which is the whole
 * risk in swapping a native control out. That means the three things a native
 * `<select>` gave away for free and a `<div>` does not:
 *
 *   - a **group name**, via `aria-labelledby` on the container, so the set is
 *     announced as "Rule preset" and `getByLabelText("Rule preset")` still
 *     resolves;
 *   - `role="radio"` + `aria-checked` per option, so each announces its state;
 *   - **arrow-key traversal** with a roving tabindex, so the group is one tab
 *     stop and the arrows move within it. Only the checked option is tabbable,
 *     which is what makes Tab skip past the group rather than through every
 *     option in it.
 *
 * "None — use my instructions" is an option here, not an absence of one. The
 * mockup omits it because its demo always has a preset selected, but prompt
 * mode is the product's default and a radiogroup with no way back to it would
 * make selecting a preset a one-way door.
 *
 * Shared with the review page's re-analysis bar, which offers the same choice.
 */

/** The sentinel for prompt mode. `null` on the wire, `""` as an option id. */
const NO_PRESET = "";

export function PresetRadioGroup({
  presets,
  value,
  onChange,
  label = "Rule preset",
  disabled = false,
  className,
}: {
  presets: Preset[];
  value: string | null;
  onChange: (preset: string | null) => void;
  label?: string;
  disabled?: boolean;
  className?: string;
}) {
  const labelId = useId();
  const optionRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const options = [
    { id: NO_PRESET, name: "None — use my instructions" },
    ...presets.map((preset) => ({ id: preset.id, name: preset.name })),
  ];

  // An unknown preset id falls back to the first option rather than leaving the
  // group with nothing tabbable, which would strip it out of the tab order.
  const selected = Math.max(
    0,
    options.findIndex((option) => option.id === (value ?? NO_PRESET))
  );

  function select(index: number) {
    onChange(options[index].id || null);
  }

  /** Arrow keys both move focus and select, which is the radiogroup contract. */
  function moveTo(index: number) {
    const next = (index + options.length) % options.length;
    select(next);
    optionRefs.current[next]?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    switch (event.key) {
      case "ArrowDown":
      case "ArrowRight":
        event.preventDefault();
        moveTo(index + 1);
        break;
      case "ArrowUp":
      case "ArrowLeft":
        event.preventDefault();
        moveTo(index - 1);
        break;
      case "Home":
        event.preventDefault();
        moveTo(0);
        break;
      case "End":
        event.preventDefault();
        moveTo(options.length - 1);
        break;
    }
  }

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span id={labelId} className="text-xs text-muted">
        {label}
      </span>
      <div
        role="radiogroup"
        aria-labelledby={labelId}
        className="flex flex-col gap-1.5"
      >
        {options.map((option, index) => {
          const isSelected = index === selected;

          return (
            <button
              key={option.id || "none"}
              ref={(node) => {
                optionRefs.current[index] = node;
              }}
              type="button"
              role="radio"
              aria-checked={isSelected}
              // The roving tabindex: one stop for the whole group.
              tabIndex={isSelected ? 0 : -1}
              disabled={disabled}
              onClick={() => select(index)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              className={cn(
                "flex items-center gap-2.5 rounded-full border px-3 py-2 text-left text-[13px] transition-colors",
                "hover:border-acc disabled:pointer-events-none disabled:opacity-50",
                isSelected ? "border-acc bg-acc-100" : "border-divider bg-transparent"
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "size-3.5 flex-none rounded-full border-[1.5px] transition-colors",
                  isSelected
                    ? "border-acc bg-acc ring-2 ring-inset ring-bg"
                    : "border-faint bg-transparent"
                )}
              />
              <span className="flex-1">{option.name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
