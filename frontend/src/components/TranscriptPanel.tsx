"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { TranscriptSegment, Violation } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { actionTextClass } from "@/lib/violations";
import { cn } from "@/lib/utils";

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
  violations: Violation[];
  currentTime: number;
  onSeek: (time: number) => void;
}

/**
 * The transcript the analysis ran on, as a readable, seekable column.
 *
 * The review list answers "what did the AI flag"; this answers "what is
 * actually in this recording" - the question you need when deciding whether a
 * suggestion has the context right, or when hunting for something the model
 * never flagged at all.
 *
 * Lines that overlap a suggested edit carry that edit's action on a 3px left
 * border and a small uppercase tag, in the same two accents the waveform's
 * regions use. A line that will actually *disappear* - an accepted cut - is
 * struck through, which is the one place on this screen where the reviewer can
 * read the finished recording rather than the edit list.
 */
export function TranscriptPanel({
  segments,
  violations,
  currentTime,
  onSeek,
}: TranscriptPanelProps) {
  const [query, setQuery] = useState("");
  const activeRef = useRef<HTMLButtonElement>(null);

  // Only pending and accepted edits colour a line. A rejected suggestion is a
  // decision the reviewer already made; re-tinting its line would keep drawing
  // the eye back to something they deliberately dismissed.
  const marks = useMemo(() => {
    return violations.filter((v) => v.status !== "rejected");
  }, [violations]);

  const activeIndex = useMemo(() => {
    return segments.findIndex((s) => currentTime >= s.start && currentTime < s.end);
  }, [segments, currentTime]);

  // Follow playback. This only fires when the active line changes, which needs
  // the playhead to move - so scrolling the panel by hand is never fought.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const needle = query.trim().toLowerCase();
  const visible = needle
    ? segments.filter((s) => s.text.toLowerCase().includes(needle))
    : segments;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-3 px-[18px] pt-4 pb-2.5">
        <h2 className="font-heading text-[19px] leading-tight">Transcript</h2>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the transcript"
          className={cn(
            "min-w-0 flex-1 rounded-full border border-divider bg-bg px-3.5 py-1.5",
            "text-[13px] text-text focus:border-acc"
          )}
        />
      </div>

      {visible.length === 0 ? (
        <p className="p-6 text-center text-[13px] text-muted">
          No lines match &ldquo;{query}&rdquo;.
        </p>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-px overflow-auto px-2 pb-3">
          {visible.map((segment, i) => {
            const isActive = segments[activeIndex] === segment;
            const mark = marks.find(
              (v) => v.start_time < segment.end && v.end_time > segment.start
            );
            const isCut = mark?.action === "cut" && mark.status === "accepted";
            return (
              <button
                key={`${segment.start}-${i}`}
                type="button"
                ref={isActive ? activeRef : undefined}
                onClick={() => onSeek(segment.start)}
                title={mark ? `${mark.label ?? "Suggested edit"} — ${mark.action}` : undefined}
                className={cn(
                  "grid grid-cols-[40px_1fr] gap-2.5 rounded-sm px-2.5 py-[7px]",
                  "border-l-[3px] text-left transition-colors hover:bg-bg",
                  isActive ? "bg-bg" : "bg-transparent",
                  !mark && "border-l-transparent",
                  mark?.action === "cut" && "border-l-acc",
                  mark?.action === "mute" && "border-l-acc2"
                )}
              >
                <span className="pt-0.5 font-mono text-[11px] font-semibold text-muted">
                  {formatTimestamp(segment.start)}
                </span>
                <span className="text-[13px] leading-snug">
                  {/*
                    The line and its tag are separate elements rather than one
                    run of text: the strike-through belongs to the words that
                    will disappear, not to the word "cut" explaining that they
                    will.
                  */}
                  <span
                    className={cn(
                      isActive ? "text-text" : "text-muted",
                      isCut && "line-through"
                    )}
                  >
                    {segment.text}
                  </span>
                  {mark && (
                    <span
                      className={cn(
                        "ml-1.5 text-[10px] font-bold tracking-[0.06em] uppercase",
                        actionTextClass(mark.action)
                      )}
                    >
                      {mark.action}
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
