"use client";

import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.js";
import { Button } from "@/components/ui/button";
import { Violation } from "@/lib/api";

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
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isReady, setIsReady] = useState(false);
  // The auto-pause timer for playClip. Held in a ref and cleared on every new
  // clip: with the clip playable from a keypress, calls overlap easily, and an
  // uncleared timer from an earlier clip would pause a later one mid-playback.
  const clipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      waveColor: "#94a3b8",
      progressColor: "#334155",
      cursorColor: "#1e293b",
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
      onTimeUpdate?.(time);
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

  // Add violation regions when ready
  useEffect(() => {
    if (!isReady || !regionsRef.current) return;

    // Clear existing regions
    regionsRef.current.clearRegions();

    // Add regions for each violation
    violations.forEach((v) => {
      const color = getActionColor(v.action, v.status);
      const region = regionsRef.current!.addRegion({
        start: v.start_time,
        end: v.end_time,
        color,
        drag: false,
        resize: false,
        id: v.id,
      });

      region.on("click", () => {
        onViolationClick(v);
      });
    });
  }, [isReady, violations, onViolationClick]);

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

  function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  return (
    <div className="space-y-4">
      {/* Waveform container */}
      <div
        ref={containerRef}
        className="w-full bg-muted/20 border rounded-md overflow-hidden"
        style={{ minHeight: 100 }}
      />

      {/* Controls */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={skipBackward}
            disabled={!isReady}
          >
            -5s
          </Button>
          <Button
            variant="secondary"
            size="lg"
            onClick={togglePlayPause}
            disabled={!isReady}
            className="w-16"
          >
            {isPlaying ? "Pause" : "Play"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={skipForward}
            disabled={!isReady}
          >
            +5s
          </Button>
        </div>

        <div className="text-xs font-mono font-medium text-muted-foreground">
          {formatTime(currentTime)} / {formatTime(duration)}
        </div>
      </div>
    </div>
  );
});

function getActionColor(
  action: string | null,
  status: string
): string {
  // Faded colors for rejected
  if (status === "rejected") {
    return "rgba(148, 163, 184, 0.1)";
  }
  
  // Accepted color
  if (status === "accepted") {
    return "rgba(148, 163, 184, 0.2)"; 
  }

  // Active colors for pending
  switch (action?.toLowerCase()) {
    case "cut":
      return "rgba(239, 68, 68, 0.15)";
    case "mute":
      return "rgba(234, 179, 8, 0.15)";
    default:
      return "rgba(148, 163, 184, 0.2)";
  }
}
