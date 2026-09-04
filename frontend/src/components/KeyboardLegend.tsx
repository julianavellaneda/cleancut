"use client";

import { cn } from "@/lib/utils";

/**
 * The shortcut reference for the review screen.
 *
 * A fixed pill at the bottom centre rather than a strip under the grid: the
 * review page scrolls, and a reference that scrolls away is one the reviewer
 * has to go looking for at exactly the moment they have forgotten a key. The
 * collapsed state still names the four keys that matter, so `?` is a way to
 * see the rest rather than the only way to see anything.
 */

const BINDINGS: [string, string][] = [
  ["J / ↓", "next"],
  ["K / ↑", "previous"],
  ["A", "accept, advance"],
  ["R", "reject, advance"],
  ["M", "cut ↔ mute"],
  ["Space", "play / pause"],
  ["P", "play clip"],
  ["T", "transcript"],
  ["?", "this list"],
];

function Key({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <kbd
      className={cn(
        "rounded-[7px] bg-bg px-1.5 py-0.5 text-center font-mono text-[11px] font-semibold text-text",
        wide && "min-w-[22px]"
      )}
    >
      {children}
    </kbd>
  );
}

export function KeyboardLegend({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="fixed bottom-4 left-1/2 z-20 -translate-x-1/2">
      {open ? (
        <div
          className={cn(
            "flex max-w-[760px] flex-wrap items-center gap-4 rounded-lg bg-surface",
            "px-5 py-3.5 text-xs text-muted shadow-lg"
          )}
        >
          {BINDINGS.map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-1.5">
              <Key wide>{key}</Key>
              {label}
            </span>
          ))}
          <button
            type="button"
            onClick={onToggle}
            aria-label="Hide keyboard shortcuts"
            className="px-0.5 text-base leading-none text-muted transition-colors hover:text-text"
          >
            ×
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "inline-flex items-center gap-2 rounded-full bg-surface px-3.5 py-1.5",
            "text-xs text-muted shadow-md transition-colors hover:text-text"
          )}
        >
          <Key>J</Key>
          <Key>K</Key>
          <Key>A</Key>
          <Key>R</Key>
          step through ·<Key>?</Key> all shortcuts
        </button>
      )}
    </div>
  );
}
