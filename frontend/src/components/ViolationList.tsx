"use client";

import { useEffect, useRef } from "react";

import { Violation } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import {
  SCRUB_LABELS,
  actionTextClass,
  cautionFlags,
  labelTintClass,
  severityTextClass,
} from "@/lib/violations";
import { cn } from "@/lib/utils";

interface ViolationListProps {
  violations: Violation[];
  selectedViolation: Violation | null;
  onSelect: (violation: Violation) => void;
  onCleanAll: () => void;
  onUndoCleanAll: () => void;
  /** True only while the last sweep is still standing and undoable. */
  canUndoCleanAll: boolean;
  isCleaning: boolean;
}

/**
 * The suggestion list, as a `44px 1fr auto` grid per row.
 *
 * Three columns because a reviewer reads a row in three fixed places: when it
 * happens, what it is, and what will become of it. A flex row let the middle
 * column's length shift the other two around, so the timestamps did not line
 * up into a column you could scan down.
 *
 * The decision is a dot rather than a tick or a cross - outlined for pending,
 * filled for accepted, faint for rejected - because the same three states are
 * drawn the same way on the waveform's legend, and a reviewer should only have
 * to learn them once.
 */
export function ViolationList({
  violations,
  selectedViolation,
  onSelect,
  onCleanAll,
  onUndoCleanAll,
  canUndoCleanAll,
  isCleaning,
}: ViolationListProps) {
  const pendingScrubCount = violations.filter(
    (v) => v.status === "pending" && v.label && SCRUB_LABELS.includes(v.label)
  ).length;

  const decisionSummary = violations.length
    ? [
        `${violations.filter((v) => v.status === "pending").length} pending`,
        `${violations.filter((v) => v.status === "accepted").length} accepted`,
        `${violations.filter((v) => v.status === "rejected").length} rejected`,
      ].join(" · ")
    : "";

  // J/K can move the selection past the fold, where the reviewer cannot see
  // what they just landed on. Follow it.
  const selectedRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedViolation?.id]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2.5 px-[18px] pt-4 pb-2.5">
        <h2 className="font-heading text-[19px] leading-tight">
          {violations.length} suggestion{violations.length === 1 ? "" : "s"}
        </h2>
        {decisionSummary && (
          <span className="text-xs text-muted">{decisionSummary}</span>
        )}
        {pendingScrubCount > 0 && (
          <button
            type="button"
            onClick={onCleanAll}
            disabled={isCleaning}
            title="Accept every pending filler word and dead-air edit"
            className={cn(
              "ml-auto rounded-full bg-acc2 px-3.5 py-1.5 font-heading text-[13px]",
              "whitespace-nowrap text-onacc transition-colors hover:bg-acc2-h",
              "disabled:pointer-events-none disabled:opacity-50"
            )}
          >
            {isCleaning ? "Cleaning…" : `Clean all ${pendingScrubCount}`}
          </button>
        )}
        {canUndoCleanAll && (
          <button
            type="button"
            onClick={onUndoCleanAll}
            disabled={isCleaning}
            title="Put the last Clean All back to pending"
            className={cn(
              "ml-auto rounded-full border border-divider px-3.5 py-1.5 text-[13px]",
              "whitespace-nowrap text-text transition-colors hover:bg-surface2",
              "disabled:pointer-events-none disabled:opacity-50"
            )}
          >
            Undo clean all
          </button>
        )}
      </div>

      {violations.length === 0 ? (
        <div className="px-6 pt-8 pb-10 text-center text-sm text-muted text-pretty">
          <div className="mx-auto mb-3 size-12 rounded-full bg-bg" />
          No edits suggested
        </div>
      ) : (
        <div
          role="listbox"
          aria-label="Suggested edits"
          className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-auto px-2 pb-2.5"
        >
          {violations.map((v) => {
            const isSelected = selectedViolation?.id === v.id;
            const cautions = cautionFlags(v);
            return (
              <div
                key={v.id}
                ref={isSelected ? selectedRef : undefined}
                role="option"
                tabIndex={0}
                aria-selected={isSelected}
                onClick={() => onSelect(v)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSelect(v);
                }}
                className={cn(
                  "grid cursor-pointer grid-cols-[44px_1fr_auto] items-center gap-2.5",
                  "rounded-md px-3 py-2.5 transition-colors outline-none",
                  isSelected
                    ? "bg-bg shadow-[inset_0_0_0_2px_var(--acc)]"
                    : "hover:bg-bg",
                  v.status === "rejected" && "opacity-55"
                )}
              >
                <span className="font-mono text-xs font-semibold text-muted">
                  {formatTimestamp(v.start_time)}
                </span>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span
                      className={cn(
                        "rounded-full px-2 py-px text-[11px] tracking-[0.04em]",
                        labelTintClass(v.label)
                      )}
                    >
                      {v.label || "Suggested Edit"}
                    </span>
                    {v.severity && (
                      <span
                        className={cn(
                          "text-[10px] font-bold tracking-[0.06em] uppercase",
                          severityTextClass(v.severity)
                        )}
                      >
                        {v.severity}
                      </span>
                    )}
                    {cautions.length > 0 && (
                      <span
                        title={cautions.map((c) => c.text).join(" ")}
                        aria-label={cautions.map((c) => c.text).join(" ")}
                        className={cn(
                          "grid size-4 place-items-center rounded-full",
                          "bg-danger-100 text-[10px] font-bold text-danger-700"
                        )}
                      >
                        !
                      </span>
                    )}
                  </div>
                  <div
                    className={cn(
                      "truncate text-[13px] text-text",
                      v.status === "rejected" && "line-through"
                    )}
                  >
                    &ldquo;{v.text}&rdquo;
                  </div>
                </div>

                <div className="flex flex-col items-end gap-[3px]">
                  <span
                    className={cn(
                      "text-[10px] tracking-[0.08em] uppercase",
                      actionTextClass(v.action)
                    )}
                  >
                    {v.action || "cut"}
                  </span>
                  <span
                    className={cn(
                      "size-2.5 rounded-full border-[1.5px]",
                      v.status === "accepted" && "border-transparent bg-acc",
                      v.status === "rejected" && "border-transparent bg-faint",
                      v.status === "pending" && "border-acc bg-transparent"
                    )}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
