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
}

export interface WaveformHandle {
  playClip: (startTime: number, endTime: number) => void;
}

export const Waveform = forwardRef<WaveformHandle, WaveformProps>(function Waveform(
  {
    audioUrl,
    violations,
    selectedViolation,
    onViolationClick,
    onTimeUpdate,
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

  // Expose playClip method to parent
  useImperativeHandle(ref, () => ({
    playClip: (startTime: number, endTime: number) => {
      if (!wavesurferRef.current || duration === 0) return;

      const start = Math.max(0, startTime - 2);
      wavesurferRef.current.seekTo(start / duration);
      wavesurferRef.current.play();

      const clipDuration = (endTime + 2 - start) * 1000;
      setTimeout(() => {
        wavesurferRef.current?.pause();
      }, clipDuration);
    },
  }), [duration]);

  // Initialize WaveSurfer
  useEffect(() => {
    if (!containerRef.current) return;

    const regions = RegionsPlugin.create();
    regionsRef.current = regions;

    const ws = WaveSurfer.create({
      container: containerRef.current,
      waveColor: "#a1a1aa",
      progressColor: "#3b82f6",
      cursorColor: "#1d4ed8",
      cursorWidth: 2,
      height: 128,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      plugins: [regions],
    });

    wavesurferRef.current = ws;

    ws.load(audioUrl);

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
      } catch (e: any) {
        // Suppress AbortError from React Strict Mode double-mount or fetch cancellation
        if (
          e.name === "AbortError" || 
          e.message?.includes("aborted") ||
          (e instanceof DOMException && e.name === "AbortError")
        ) {
          return;
        }
        throw e;
      }
    };
  }, [audioUrl]);

  // Add violation regions when ready
  useEffect(() => {
    if (!isReady || !regionsRef.current) return;

    // Clear existing regions
    regionsRef.current.clearRegions();

    // Add regions for each violation
    violations.forEach((v) => {
      const color = getSeverityColor(v.severity, v.status);
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

    // Seek to the violation
    wavesurferRef.current.seekTo(selectedViolation.start_time / duration);
  }, [selectedViolation, isReady, duration]);

  const togglePlayPause = useCallback(() => {
    wavesurferRef.current?.playPause();
  }, []);

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
        className="w-full bg-muted/30 rounded-lg"
        style={{ minHeight: 128 }}
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
            variant="default"
            size="lg"
            onClick={togglePlayPause}
            disabled={!isReady}
            className="w-16"
          >
            {isPlaying ? "⏸" : "▶"}
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

        <div className="text-sm font-mono">
          {formatTime(currentTime)} / {formatTime(duration)}
        </div>
      </div>
    </div>
  );
});

function getSeverityColor(
  severity: string | null,
  status: string
): string {
  // Faded colors for rejected/accepted
  if (status === "rejected") {
    return "rgba(128, 128, 128, 0.2)";
  }
  if (status === "accepted") {
    return "rgba(34, 197, 94, 0.3)"; // Green for accepted
  }

  // Active colors for pending
  switch (severity?.toLowerCase()) {
    case "high":
      return "rgba(239, 68, 68, 0.4)"; // Red
    case "medium":
      return "rgba(234, 179, 8, 0.4)"; // Yellow
    case "low":
      return "rgba(59, 130, 246, 0.4)"; // Blue
    default:
      return "rgba(156, 163, 175, 0.4)"; // Gray
  }
}
