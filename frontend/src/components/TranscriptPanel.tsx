"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { TranscriptSegment, Violation } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TranscriptPanelProps {
  segments: TranscriptSegment[];
  violations: Violation[];
  currentTime: number;
  onSeek: (time: number) => void;
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * The transcript the analysis ran on, as a readable, seekable column.
 *
 * The review list answers "what did the AI flag"; this answers "what is
 * actually in this recording" - the question you need when deciding whether a
 * suggestion has the context right, or when hunting for something the model
 * never flagged at all.
 *
 * Lines that overlap a suggested edit carry that edit's colour, so the flagged
 * moments are findable from the text rather than only from the waveform.
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
    <div className="h-full flex flex-col">
      <div className="p-4 border-b space-y-3">
        <h3 className="font-semibold text-sm">Transcript</h3>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search the transcript…"
          className="w-full rounded-md border bg-background px-3 py-1.5 text-xs"
        />
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="p-2">
          {visible.length === 0 ? (
            <p className="p-4 text-xs text-muted-foreground">
              No lines match “{query}”.
            </p>
          ) : (
            visible.map((segment, i) => {
              const isActive = segments[activeIndex] === segment;
              const mark = marks.find(
                (v) => v.start_time < segment.end && v.end_time > segment.start
              );
              return (
                <button
                  key={`${segment.start}-${i}`}
                  type="button"
                  ref={isActive ? activeRef : undefined}
                  onClick={() => onSeek(segment.start)}
                  title={mark ? `${mark.label ?? "Suggested edit"} — ${mark.action}` : undefined}
                  className={cn(
                    "w-full rounded-md border-l-2 px-3 py-2 text-left transition-colors",
                    "hover:bg-surface2/60",
                    isActive ? "bg-surface2" : "bg-transparent",
                    !mark && "border-l-transparent",
                    mark?.action === "cut" && "border-l-destructive",
                    mark?.action === "mute" && "border-l-amber-500"
                  )}
                >
                  <span className="mr-2 font-mono text-[10px] text-muted-foreground">
                    {formatTime(segment.start)}
                  </span>
                  <span
                    className={cn(
                      "text-xs leading-relaxed",
                      isActive ? "text-foreground" : "text-muted-foreground"
                    )}
                  >
                    {segment.text}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
