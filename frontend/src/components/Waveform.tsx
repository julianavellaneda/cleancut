"use client";

import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.js";

import { PauseGlyph, PlayGlyph, SkipBackGlyph, SkipForwardGlyph } from "@/components/icons";
import { useTheme } from "@/components/ThemeToggle";
import { Violation } from "@/lib/api";
import { formatTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

interface WaveformProps {
  audioUrl: string;
  violations: Violation[];
  selectedViolation: Violation | null;
  onViolationClick: (violation: Violation) => void;
  onTimeUpdate?: (time: number) => void;
  mediaRef?: React.RefObject<HTMLMediaElement | null>;
}

export interface WaveformHandle {
  playClip: (startTime: number, endTime: number) => void;
  togglePlayPause: () => void;
  seekTo: (time: number) => void;
}

/**
 * What a region says, and why it is the action rather than the severity.
 *
 * The waveform is where an editor reads *what will happen to the file*, and
 * that is decided by `action`: a cut shortens the recording, a mute leaves the
 * timeline intact. Severity is a judgement about the content and it moved to a
 * word in the list and the detail panel, where a word is what it always was.
 * Keying a colour off it here meant the one picture of the finished edit said
 * nothing about the edit.
 *
 * `status` rides on top as opacity and fill: a pending span is the tint, an
 * accepted one is the solid accent, a rejected one fades to `--faint` but keeps
 * its place - it is still a thing the reviewer decided about.
 *
 * The colours are `var(--…)` strings rather than resolved values, so a theme
 * flip repaints them with no work from us. Only the waveform *canvas* needs
 * resolved colours, because a canvas fill cannot read a custom property.
 */
function regionFill(
  action: string | null,
  status: string
): { color: string; backgroundImage: string; borderLeftColor: string } {
  const isCut = action?.toLowerCase() !== "mute";
  const accent = isCut ? "var(--acc)" : "var(--acc2)";
  const tint = isCut ? "var(--acc-200)" : "var(--acc2-200)";
  const rejected = status === "rejected";

  return {
    color: rejected ? "var(--faint)" : status === "accepted" ? accent : tint,
    // The hatch is what tells a mute from a cut without relying on hue alone -
    // the two accents are a violet and a blue, which is exactly the pair a
    // deuteranopic reviewer has least to work with.
    backgroundImage:
      !isCut && !rejected
        ? "repeating-linear-gradient(135deg, transparent 0 3px, var(--surface) 3px 5px)"
        : "none",
    borderLeftColor: rejected ? "transparent" : accent,
  };
}

/**
 * Emphasis, kept apart from fill because it changes far more often.
 *
 * The selection moves on every `J`; the edit list moves only on a decision. If
 * the two shared an effect, holding `J` down would tear every region off the
 * DOM and rebuild it to brighten one of them.
 */
function regionOpacity(status: string, isSelected: boolean): string {
  if (status === "rejected") return "0.35";
  return isSelected ? "1" : "0.8";
}

/** The three canvas colours, resolved - a canvas fill cannot read `var()`. */
function readCanvasColors(el: HTMLElement): Partial<{
  waveColor: string;
  progressColor: string;
  cursorColor: string;
}> {
  const style = window.getComputedStyle(el);
  const read = (name: string) => style.getPropertyValue(name).trim();
  const options: Record<string, string> = {};
  // Each is omitted rather than defaulted when the sheet has not loaded: a
  // literal here would be the one colour in the app the token sheet did not own.
  const waveColor = read("--faint");
  const progressColor = read("--acc");
  const cursorColor = read("--text");
  if (waveColor) options.waveColor = waveColor;
  if (progressColor) options.progressColor = progressColor;
  if (cursorColor) options.cursorColor = cursorColor;
  return options;
}

function TransportButton({
  label,
  onClick,
  disabled,
  primary,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  primary?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "grid shrink-0 place-items-center rounded-full transition-colors",
        "disabled:pointer-events-none disabled:opacity-45",
        primary
          ? "size-11 bg-acc text-onacc hover:bg-acc-h"
          : "size-9 border border-divider text-text hover:bg-bg"
      )}
    >
      {children}
    </button>
  );
}

function LegendSwatch({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={className} aria-hidden />
      {children}
    </span>
  );
}

export const Waveform = forwardRef<WaveformHandle, WaveformProps>(function Waveform(
  {
    audioUrl,
    violations,
    selectedViolation,
    onViolationClick,
    onTimeUpdate,
    mediaRef,
  },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wavesurferRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPlugin | null>(null);
  // The drawn region elements by suggestion id, so emphasis can be re-applied
  // without going back through the plugin to rebuild them.
  const regionElementsRef = useRef<Map<string, HTMLElement>>(new Map());
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isReady, setIsReady] = useState(false);
  const [theme] = useTheme();
  // The auto-pause timer for playClip. Held in a ref and cleared on every new
  // clip: with the clip playable from a keypress, calls overlap easily, and an
  // uncleared timer from an earlier clip would pause a later one mid-playback.
  const clipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The parent's time callback, read through a ref by the "timeupdate" handler
  // below. Calling the prop directly would put it in the initialization effect's
  // dependencies, and that effect *creates and destroys WaveSurfer* - so a
  // parent that passed an unmemoized function would tear down the player and
  // reload the audio on every one of its renders. Through a ref, the handler
  // always calls the current callback and the player is built once per source.
  const onTimeUpdateRef = useRef(onTimeUpdate);
  useEffect(() => {
    onTimeUpdateRef.current = onTimeUpdate;
  }, [onTimeUpdate]);

  const togglePlayPause = useCallback(() => {
    wavesurferRef.current?.playPause();
  }, []);

  // Expose playback control to the parent, which drives it from the keyboard.
  useImperativeHandle(ref, () => ({
    playClip: (startTime: number, endTime: number) => {
      if (!wavesurferRef.current || duration === 0) return;

      if (clipTimerRef.current) clearTimeout(clipTimerRef.current);

      const start = Math.max(0, startTime - 0.5);

      if (mediaRef?.current) {
        mediaRef.current.currentTime = start;
        mediaRef.current.play();
      } else {
        wavesurferRef.current.seekTo(start / duration);
        wavesurferRef.current.play();
      }

      // Pause automatically after the clip
      const clipDuration = (endTime + 0.5 - start) * 1000;
      clipTimerRef.current = setTimeout(() => {
        clipTimerRef.current = null;
        if (mediaRef?.current) {
          mediaRef.current.pause();
        } else {
          wavesurferRef.current?.pause();
        }
      }, clipDuration);
    },
    seekTo: (time: number) => {
      if (!wavesurferRef.current || duration === 0) return;
      // A pending clip timer belongs to the clip the user just left; letting it
      // fire would pause playback a second or two after this seek.
      if (clipTimerRef.current) {
        clearTimeout(clipTimerRef.current);
        clipTimerRef.current = null;
      }
      const target = Math.max(0, Math.min(duration, time));
      if (mediaRef?.current) {
        mediaRef.current.currentTime = target;
      } else {
        wavesurferRef.current.seekTo(target / duration);
      }
    },
    togglePlayPause,
  }), [duration, mediaRef, togglePlayPause]);

  useEffect(() => () => {
    if (clipTimerRef.current) clearTimeout(clipTimerRef.current);
  }, []);

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current) return;

    const regions = RegionsPlugin.create();
    regionsRef.current = regions;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      ...readCanvasColors(containerRef.current),
      cursorWidth: 2,
      height: 100,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      media: mediaRef?.current || undefined,
      plugins: [regions],
    });

    wavesurferRef.current = ws;

    if (!mediaRef?.current) {
      ws.load(audioUrl);
    }

    ws.on("ready", () => {
      setDuration(ws.getDuration());
      setIsReady(true);
    });

    ws.on("timeupdate", (time) => {
      setCurrentTime(time);
      onTimeUpdateRef.current?.(time);
    });

    ws.on("play", () => setIsPlaying(true));
    ws.on("pause", () => setIsPlaying(false));
    ws.on("finish", () => setIsPlaying(false));

    return () => {
      try {
        ws.destroy();
      } catch (e: unknown) {
        if (
          e instanceof Error &&
          (e.name === "AbortError" || 
           e.message?.includes("aborted"))
        ) {
          return;
        }
        throw e;
      }
    };
  }, [audioUrl, mediaRef]);

  /*
   * A theme flip repaints the canvas, and only the canvas.
   *
   * WaveSurfer takes its colours at construction and bakes them into a canvas
   * gradient, so the peaks would keep the old theme's ink until something else
   * happened to rebuild the player. `setOptions` is the whole fix - rebuilding
   * the instance would re-fetch and re-decode the audio to change three
   * colours, and would drop the playhead on the floor while it did.
   */
  useEffect(() => {
    if (!containerRef.current || !wavesurferRef.current) return;
    wavesurferRef.current.setOptions(readCanvasColors(containerRef.current));
  }, [theme]);

  // Add violation regions when ready
  useEffect(() => {
    if (!isReady || !regionsRef.current) return;

    // Clear existing regions
    regionsRef.current.clearRegions();

    regionElementsRef.current.clear();

    // Add regions for each violation
    violations.forEach((v) => {
      const fill = regionFill(v.action, v.status);
      const region = regionsRef.current!.addRegion({
        start: v.start_time,
        end: v.end_time,
        color: fill.color,
        drag: false,
        resize: false,
        id: v.id,
      });

      // The plugin only knows about `color`; the hatch and the edge go on the
      // element it hands back. A short edit can round to sub-pixel width, so it
      // is also given a floor here - an invisible region is worse than a
      // slightly wide one.
      const element = region.element;
      if (element) {
        element.style.backgroundImage = fill.backgroundImage;
        element.style.borderLeft = `2px solid ${fill.borderLeftColor}`;
        element.style.minWidth = "3px";
        regionElementsRef.current.set(v.id, element);
      }

      region.on("click", () => {
        onViolationClick(v);
      });
    });
  }, [isReady, violations, onViolationClick]);

  // Brighten the region under review, without touching the ones that are not.
  useEffect(() => {
    violations.forEach((v) => {
      const element = regionElementsRef.current.get(v.id);
      if (element) {
        element.style.opacity = regionOpacity(v.status, v.id === selectedViolation?.id);
      }
    });
  }, [isReady, violations, selectedViolation?.id]);

  // Highlight selected violation
  useEffect(() => {
    if (!isReady || !selectedViolation || !wavesurferRef.current || duration === 0) return;

    // Seek to the violation (with small buffer)
    wavesurferRef.current.seekTo(Math.max(0, selectedViolation.start_time - 0.2) / duration);
  }, [selectedViolation, isReady, duration]);

  const skipBackward = useCallback(() => {
    if (!wavesurferRef.current || duration === 0) return;
    const newTime = Math.max(0, currentTime - 5);
    wavesurferRef.current.seekTo(newTime / duration);
  }, [currentTime, duration]);

  const skipForward = useCallback(() => {
    if (!wavesurferRef.current || duration === 0) return;
    const newTime = Math.min(duration, currentTime + 5);
    wavesurferRef.current.seekTo(newTime / duration);
  }, [currentTime, duration]);

  return (
    <div className="flex flex-col gap-3">
      <div
        ref={containerRef}
        className="w-full overflow-hidden rounded-sm bg-bg"
        style={{ minHeight: 100 }}
      />

      <div className="flex flex-wrap items-center gap-2">
        <TransportButton label="-5s" onClick={skipBackward} disabled={!isReady}>
          <SkipBackGlyph size={15} />
        </TransportButton>
        <TransportButton
          label={isPlaying ? "Pause" : "Play"}
          onClick={togglePlayPause}
          disabled={!isReady}
          primary
        >
          {isPlaying ? <PauseGlyph /> : <PlayGlyph />}
        </TransportButton>
        <TransportButton label="+5s" onClick={skipForward} disabled={!isReady}>
          <SkipForwardGlyph size={15} />
        </TransportButton>

        <span className="ml-1.5 shrink-0 font-mono text-[13px] font-semibold whitespace-nowrap text-muted">
          {formatTimestamp(currentTime)} / {formatTimestamp(duration)}
        </span>

        {!isReady && (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-xs whitespace-nowrap text-muted">
            <span className="size-2.5 animate-cc-spin rounded-full border-2 border-faint border-t-transparent" />
            loading audio…
          </span>
        )}

        {/*
          The legend is the difference between a convention and folklore. The
          regions encode two things at once and neither is guessable.
        */}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-3 text-[11px] whitespace-nowrap text-muted">
          <LegendSwatch className="h-2 w-3.5 rounded-[3px] bg-acc">cut</LegendSwatch>
          {/* The hatch alone, with no fill behind it - a solid `bg-acc2` under
              the gradient's transparent gaps would fill them back in and the
              swatch would stop being the thing it is describing. */}
          <LegendSwatch className="h-2 w-3.5 rounded-[3px] bg-[repeating-linear-gradient(135deg,var(--acc2)_0_2px,transparent_2px_4px)]">
            mute
          </LegendSwatch>
          <LegendSwatch className="size-2 rounded-full border-[1.5px] border-acc">
            pending
          </LegendSwatch>
          <LegendSwatch className="size-2 rounded-full bg-acc">accepted</LegendSwatch>
          <LegendSwatch className="size-2 rounded-full bg-faint">rejected</LegendSwatch>
        </div>
      </div>
    </div>
  );
});
