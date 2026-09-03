"use client";

import { Violation } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { PlayGlyph } from "@/components/icons";
import { cautionFlags, labelTintClass, severityTextClass } from "@/lib/violations";
import { cn } from "@/lib/utils";

interface ViolationCardProps {
  violation: Violation;
  /** 1-based position in the list on the left, and its length. */
  index: number;
  total: number;
  onAccept: () => void;
  onReject: () => void;
  onActionChange: (action: "cut" | "mute") => void;
  onPlayClip: () => void;
  isUpdating: boolean;
}

function Kbd({ children, onAccent }: { children: React.ReactNode; onAccent?: boolean }) {
  return (
    <kbd
      className={cn(
        "rounded-[5px] px-1.5 py-px font-mono text-[10px] font-semibold",
        // A scrim of the button's own foreground, not white: on the accent
        // button `--onacc` is the light in one theme and the dark in the other.
        onAccent ? "bg-onacc/20" : "bg-bg"
      )}
    >
      {children}
    </kbd>
  );
}

/**
 * The detail panel for one suggestion.
 *
 * Its whole visual idea is the quote: set as a display-face blockquote rather
 * than as another 13px line, because the words that will be removed from the
 * recording are the one thing the reviewer is actually deciding about. Every
 * other field on this panel exists to qualify that sentence.
 *
 * The cut/mute control names its consequence on each option - "shortens" and
 * "keeps timing" - rather than leaving the reviewer to remember which is which.
 * The two are destructive in different ways and the difference is not in the
 * words "cut" and "mute" for anyone who has not read the export code.
 */
export function ViolationCard({
  violation,
  index,
  total,
  onAccept,
  onReject,
  onActionChange,
  onPlayClip,
  isUpdating,
}: ViolationCardProps) {
  const action = violation.action?.toLowerCase() === "mute" ? "mute" : "cut";
  const flags = cautionFlags(violation);
  const length = `${(violation.end_time - violation.start_time).toFixed(1)}s`;

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-2.5 py-0.5 text-xs tracking-[0.04em]",
                labelTintClass(violation.label)
              )}
            >
              {violation.label || "Suggested Edit"}
            </span>
            {violation.severity && (
              <span
                className={cn(
                  "text-[11px] font-bold tracking-[0.06em] uppercase",
                  severityTextClass(violation.severity)
                )}
              >
                {violation.severity} severity
              </span>
            )}
            <span className="text-xs text-muted">
              {index} of {total}
            </span>
          </div>
          {violation.rule_violated && (
            <div className="text-[13px] text-muted">
              Rule: <span className="text-text">{violation.rule_violated}</span>
            </div>
          )}
        </div>
        <span className="shrink-0 font-mono text-[13px] font-semibold text-muted">
          {formatTimestamp(violation.start_time)} → {formatTimestamp(violation.end_time)}{" "}
          ({length})
        </span>
      </div>

      <blockquote className="font-heading text-2xl leading-tight tracking-[-0.01em] text-pretty [overflow-wrap:anywhere]">
        &ldquo;{violation.text}&rdquo;
      </blockquote>

      {violation.reasoning && (
        <p className="text-sm leading-relaxed text-muted text-pretty">
          {violation.reasoning}
        </p>
      )}

      {/*
        Why this one was never applied unreviewed. One row per flag, in the
        danger tint, and strictly one-way: `ViolationUpdate` cannot carry these,
        so nothing on this screen can clear a doubt the detector recorded.
      */}
      {flags.length > 0 && (
        <div className="flex flex-col gap-2">
          {flags.map((f) => (
            <div
              key={f.name}
              className="flex items-start gap-3 rounded-md bg-danger-100 px-3.5 py-2.5 text-[13px] text-danger-700"
            >
              <span className="shrink-0 pt-0.5 text-[11px] font-bold tracking-[0.06em] whitespace-nowrap uppercase">
                {f.name}
              </span>
              <span className="text-pretty">{f.text}</span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-3.5 border-t border-divider pt-3">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] tracking-[0.06em] text-muted uppercase">
            On export
          </span>
          <div
            role="group"
            aria-label="On export"
            className="inline-flex overflow-hidden rounded-full border border-divider"
          >
            {([
              ["cut", "shortens"],
              ["mute", "keeps timing"],
            ] as const).map(([a, consequence], i) => (
              <button
                key={a}
                type="button"
                aria-pressed={action === a}
                onClick={() => onActionChange(a)}
                disabled={isUpdating}
                className={cn(
                  "px-3.5 py-1.5 text-[13px] capitalize transition-colors",
                  "disabled:pointer-events-none disabled:opacity-50",
                  i > 0 && "border-l border-divider",
                  action === a ? "bg-acc text-onacc" : "text-text hover:bg-bg"
                )}
              >
                {a} <span className="text-[11px]">{consequence}</span>
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          onClick={onPlayClip}
          className={cn(
            "inline-flex items-center gap-1.5 self-end rounded-full border border-divider",
            "px-3.5 py-2 text-[13px] text-text transition-colors hover:bg-bg"
          )}
        >
          <PlayGlyph size={12} />
          Play clip <Kbd>P</Kbd>
        </button>

        <div className="ml-auto flex items-center gap-2 self-end">
          {violation.status === "pending" ? (
            <>
              <button
                type="button"
                onClick={onReject}
                disabled={isUpdating}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full border border-divider",
                  "px-4 py-2.5 text-sm text-text transition-colors hover:bg-bg",
                  "disabled:pointer-events-none disabled:opacity-50"
                )}
              >
                Reject <Kbd>R</Kbd>
              </button>
              <button
                type="button"
                onClick={onAccept}
                disabled={isUpdating}
                className={cn(
                  "inline-flex items-center gap-2 rounded-full bg-acc px-5 py-2.5",
                  "font-heading text-[15px] text-onacc transition-colors hover:bg-acc-h",
                  "disabled:pointer-events-none disabled:opacity-50"
                )}
              >
                Accept <Kbd onAccent>A</Kbd>
              </button>
            </>
          ) : (
            <>
              <span
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-[13px] font-semibold",
                  violation.status === "accepted"
                    ? "bg-acc-200 text-acc-700"
                    : "bg-surface2 text-muted"
                )}
              >
                {violation.status === "accepted"
                  ? `Accepted · will ${action}`
                  : "Rejected · untouched"}
              </span>
              <button
                type="button"
                onClick={violation.status === "accepted" ? onReject : onAccept}
                disabled={isUpdating}
                className={cn(
                  "rounded-full border border-divider px-3.5 py-2 text-[13px]",
                  "text-text transition-colors hover:bg-bg",
                  "disabled:pointer-events-none disabled:opacity-50"
                )}
              >
                Undo
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
