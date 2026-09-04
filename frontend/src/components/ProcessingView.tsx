"use client";

import Link from "next/link";

import { ArrowLeftGlyph } from "@/components/icons";
import { Job } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The pipeline, in the order `services/worker.py` walks it. Every stage is
 * rendered every time - a job that skips one should read as "skipped", not as
 * a stage that vanished, and the shape of the pipeline is the point of the
 * screen.
 */
const STAGES = [
  {
    id: "converting",
    label: "Converting",
    caption: "Transcoding the upload to a format Whisper can read",
  },
  {
    id: "transcribing",
    label: "Transcribing",
    caption: "Listening to the recording and timing every word",
  },
  {
    id: "analyzing",
    label: "Analyzing",
    caption: "Reading the transcript against your instructions",
  },
  {
    id: "exporting",
    label: "Exporting",
    caption: "Rendering the pre-accepted edits",
  },
  {
    id: "completed",
    label: "Ready to review",
    caption: "",
  },
] as const;

type StageState = "done" | "active" | "pending" | "skipped";

/** Only AIFF uploads are transcoded - see the worker's step 0. */
function willConvert(job: Job): boolean {
  const name = job.original_filename || job.filename || "";
  return /\.aiff?$/i.test(name);
}

/** The worker only exports up front when it has edits pre-accepted for it. */
function willExport(job: Job): boolean {
  return Boolean(job.auto_fix || job.auto_scrub);
}

function stageStates(job: Job): StageState[] {
  const applicable = STAGES.map((stage) => {
    if (stage.id === "converting") return willConvert(job);
    if (stage.id === "exporting") return willExport(job);
    return true;
  });

  const current = STAGES.findIndex((stage) => stage.id === job.status);

  return STAGES.map((_, i) => {
    if (!applicable[i]) return "skipped";
    // `pending` means queued: the worker has not picked the job up, so no
    // stage has started and none should claim to be running.
    if (current === -1) return "pending";
    if (i < current) return "done";
    if (i === current) return "active";
    return "pending";
  });
}

/**
 * The dot carries the state on its own, so the uppercase label beside it is
 * confirmation rather than the only signal. The active one pulses - the single
 * piece of motion on the screen, and the thing that says a still-looking page
 * is going to change by itself.
 */
function StageDot({ state }: { state: StageState }) {
  return (
    <span
      className={cn(
        "size-3.5 flex-none rounded-full border-2",
        state === "done" && "border-acc bg-acc",
        state === "active" && "border-acc bg-acc animate-cc-pulse",
        state === "pending" && "border-divider bg-transparent",
        state === "skipped" && "border-divider bg-surface2"
      )}
    />
  );
}

/**
 * Every stage says where it stands, including the ones that have not started.
 * A blank beside four of five stages read as a rendering fault rather than as
 * "not yet".
 */
function stateLabel(stageId: string, state: StageState): string {
  if (state === "done") return "done";
  if (state === "active") return "running";
  if (state === "skipped") return stageId === "exporting" ? "not required" : "skipped";
  return "waiting";
}

export function ProcessingView({ job }: { job: Job }) {
  const states = stageStates(job);
  const isQueued = states.indexOf("active") === -1;

  const meta = [
    job.media_type === "video" ? "Video" : "Audio",
    job.duration_seconds ? formatDuration(job.duration_seconds) : null,
    job.preset ? `${job.preset} preset` : job.prompt ? "prompt mode" : null,
  ].filter(Boolean);

  return (
    <div className="flex min-h-screen items-center justify-center px-8 py-16">
      <div className="flex w-full max-w-[640px] flex-col gap-9">
        <div>
          <Link
            href="/"
            className="mb-4 inline-flex items-center gap-1.5 text-[13px] text-muted no-underline transition-colors hover:text-acc"
          >
            <ArrowLeftGlyph size={13} />
            All recordings
          </Link>
          <h1 className="mb-2 font-heading text-[30px] leading-tight [overflow-wrap:anywhere]">
            {job.original_filename || job.filename}
          </h1>
          <p className="text-sm text-muted">{meta.join(" · ")}</p>
        </div>

        {isQueued && (
          <div className="flex items-center gap-3 rounded-lg bg-surface px-5 py-3.5 text-sm">
            <span className="size-2.5 flex-none rounded-full bg-acc animate-cc-pulse" />
            Queued — waiting for the worker to pick this up. No stage has started yet.
          </div>
        )}

        <ol className="flex flex-col">
          {STAGES.map((stage, i) => {
            const state = states[i];
            const isLast = i === STAGES.length - 1;

            return (
              // No opacity wash for the inactive states: over --muted it
              // measured 2.8:1 (pending) and 1.9:1 (skipped). The dot, the
              // --muted title and the state word already say where a stage
              // stands, and they all stay readable.
              <li
                key={stage.id}
                className="grid grid-cols-[28px_1fr_auto] items-start gap-4.5 py-3.5"
              >
                <div className="flex h-full flex-col items-center gap-1.5">
                  <StageDot state={state} />
                  {/* The rail between this stage and the next. */}
                  {!isLast && (
                    <span aria-hidden className="w-0.5 min-h-[22px] flex-1 rounded-sm bg-divider" />
                  )}
                </div>

                <div className="min-w-0">
                  <div
                    className={cn(
                      "font-heading text-[19px] leading-tight",
                      state === "pending" || state === "skipped" ? "text-muted" : "text-text"
                    )}
                  >
                    {stage.label}
                  </div>
                  {stage.caption && (
                    <div className="text-[13px] text-muted text-pretty">{stage.caption}</div>
                  )}
                </div>

                <span
                  className={cn(
                    "pt-1 text-[11px] uppercase tracking-[0.08em]",
                    state === "active" ? "text-acc" : "text-muted"
                  )}
                >
                  {stateLabel(stage.id, state)}
                </span>
              </li>
            );
          })}
        </ol>

        <p className="flex items-center gap-2 text-xs text-muted">
          <span className="size-1.5 flex-none rounded-full bg-acc animate-cc-pulse" />
          This page checks for progress every 2 seconds. You can leave it open and walk away.
        </p>
      </div>
    </div>
  );
}
