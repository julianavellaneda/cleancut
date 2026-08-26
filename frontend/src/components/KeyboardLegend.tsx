"use client";

/**
 * The shortcut reference for the review screen.
 *
 * Collapsed to a single hint by default so it never competes with the
 * suggestion under review; `?` expands it.
 */

const BINDINGS: [string, string][] = [
  ["J / ↓", "Next suggestion"],
  ["K / ↑", "Previous suggestion"],
  ["A", "Accept and advance"],
  ["R", "Reject and advance"],
  ["M", "Toggle cut / mute"],
  ["Space", "Play / pause"],
  ["P", "Play the selected clip"],
  ["?", "Hide this list"],
];

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border bg-background px-1.5 py-0.5 font-mono text-[10px] font-semibold shadow-sm">
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
  if (!open) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className="border-t px-8 py-2 text-left text-[11px] text-muted-foreground hover:text-foreground transition-colors"
      >
        <Key>?</Key> <span className="ml-2">Keyboard shortcuts</span>
      </button>
    );
  }

  return (
    <div className="border-t bg-muted/20 px-8 py-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {BINDINGS.map(([key, label]) => (
          <div key={key} className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <Key>{key}</Key>
            <span>{label}</span>
          </div>
        ))}
        <button
          type="button"
          onClick={onToggle}
          className="ml-auto text-[11px] underline text-muted-foreground hover:text-foreground"
        >
          Hide
        </button>
      </div>
    </div>
  );
}
