"use client";

import { useEffect, useRef, useState } from "react";

import { PauseGlyph, PlayGlyph } from "@/components/icons";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ExportPreviewProps {
  src: string;
  /** How many accepted edits went into the render, and what they removed. */
  editCount: number;
  secondsRemoved: number;
}

/**
 * The rendered export, as a strip rather than a browser's default player.
 *
 * The point of the strip is the line under the title: a native `<audio>`
 * control says a file exists and nothing about what is in it, and "3 edits
 * applied · 4.2s removed" is the only confirmation on this screen that the
 * render matched the decisions the reviewer made.
 *
 * The scrubber is a real `<input type="range">` and not the mockup's decorative
 * bar. Dropping the native controls for a play button alone would have taken
 * seeking away from a preview whose whole job is spot-checking a cut, and a
 * range input is the one control that is draggable, arrow-key steppable and
 * announced as a slider without any of it being rebuilt here.
 */
export function ExportPreview({ src, editCount, secondsRemoved }: ExportPreviewProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // The element is the source of truth for all three: it also moves when
  // playback ends on its own, or when the file finishes loading.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onTime = () => setCurrentTime(audio.currentTime);
    const onMeta = () => setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onMeta);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onPause);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onMeta);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onPause);
    };
  }, [src]);

  return (
    <div className="flex flex-wrap items-center gap-3.5 rounded-lg bg-acc2-100 px-[18px] py-3.5 text-acc2-700">
      <audio ref={audioRef} src={src} preload="metadata" className="hidden" />

      <button
        type="button"
        aria-label={isPlaying ? "Pause the edited result" : "Play the edited result"}
        onClick={() => {
          const audio = audioRef.current;
          if (!audio) return;
          if (audio.paused) audio.play();
          else audio.pause();
        }}
        className="grid size-9.5 shrink-0 place-items-center rounded-full bg-acc2 text-onacc transition-colors hover:bg-acc2-h"
      >
        {isPlaying ? <PauseGlyph size={14} /> : <PlayGlyph size={14} />}
      </button>

      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">Edited result</div>
        <div className="text-xs opacity-80">
          {editCount} edit{editCount === 1 ? "" : "s"} applied ·{" "}
          {secondsRemoved.toFixed(1)}s removed
        </div>
      </div>

      <input
        type="range"
        aria-label="Seek the edited result"
        min={0}
        max={duration || 0}
        step={0.1}
        value={Math.min(currentTime, duration || 0)}
        disabled={duration === 0}
        onChange={(e) => {
          const audio = audioRef.current;
          if (audio) audio.currentTime = Number(e.target.value);
        }}
        className={cn(
          "h-1 min-w-32 flex-1 cursor-pointer appearance-none rounded-sm bg-acc2-300",
          "disabled:cursor-default disabled:opacity-50",
          "[&::-webkit-slider-thumb]:size-3 [&::-webkit-slider-thumb]:appearance-none",
          "[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-acc2",
          "[&::-moz-range-thumb]:size-3 [&::-moz-range-thumb]:rounded-full",
          "[&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:bg-acc2"
        )}
      />

      <span className="shrink-0 font-mono text-xs font-semibold">
        {formatTimestamp(currentTime)} / {formatTimestamp(duration)}
      </span>
    </div>
  );
}
