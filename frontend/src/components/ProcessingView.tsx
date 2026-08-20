"use client";

import { Job } from "@/lib/api";
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

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function StageDot({ state }: { state: StageState }) {
  if (state === "done") {
    return <div className="size-3 rounded-full bg-foreground" />;
  }
  if (state === "active") {
    return (
      <div className="size-3 rounded-full bg-foreground ring-4 ring-foreground/15" />
    );
  }
  if (state === "skipped") {
    return <div className="size-3 rounded-full border border-border bg-muted" />;
  }
  return <div className="size-3 rounded-full border border-border" />;
}

function stateLabel(stageId: string, state: StageState): string {
  if (state === "done") return "done";
  if (state === "skipped") return stageId === "exporting" ? "not required" : "skipped";
  return "";
}

export function ProcessingView({ job }: { job: Job }) {
  const states = stageStates(job);
  const activeIndex = states.indexOf("active");
  const isQueued = activeIndex === -1;

  const meta = [
    job.media_type === "video" ? "Video" : "Audio",
    job.duration_seconds ? formatDuration(job.duration_seconds) : null,
    job.preset ? `${job.preset} preset` : job.prompt ? "prompt mode" : null,
  ].filter(Boolean);

  return (
    <div className="min-h-screen flex items-center justify-center px-8 py-16">
      <div className="w-full max-w-2xl space-y-10">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight truncate">
            {job.original_filename || job.filename}
          </h1>
          <p className="text-sm text-muted-foreground">{meta.join(" · ")}</p>
        </div>

        {isQueued && (
          <div className="space-y-3">
            <p className="text-base">Queued</p>
            <div className="h-[3px] w-full overflow-hidden rounded-full bg-border">
              <div className="h-full w-1/5 rounded-full bg-foreground/50 animate-stage-sweep" />
            </div>
            <p className="text-sm text-muted-foreground">
              Waiting for a worker to pick this recording up
            </p>
          </div>
        )}

        <ol className="relative">
          {STAGES.map((stage, i) => {
            const state = states[i];
            const isLast = i === STAGES.length - 1;

            return (
              <li key={stage.id} className="relative flex gap-5 pb-8 last:pb-0">
                {/* Rail between this stage and the next. */}
                {!isLast && (
                  <span
                    aria-hidden
                    className={cn(
                      "absolute left-[5px] top-4 h-[calc(100%-1rem)] w-px",
                      state === "done" ? "bg-foreground/40" : "bg-border"
                    )}
                  />
                )}

                <div className="relative z-10 mt-1.5 shrink-0">
                  <StageDot state={state} />
                </div>

                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex items-baseline justify-between gap-4">
                    <span
                      className={cn(
                        "text-base",
                        state === "active" && "font-semibold",
                        state === "done" && "text-foreground",
                        state === "pending" && "text-muted-foreground",
                        state === "skipped" && "text-muted-foreground/60"
                      )}
                    >
                      {stage.label}
                    </span>
                    <span className="shrink-0 text-sm text-muted-foreground tabular-nums">
                      {stateLabel(stage.id, state)}
                    </span>
                  </div>

                  {state === "active" && (
                    <div className="space-y-2 pt-0.5">
                      <div className="h-[3px] w-full overflow-hidden rounded-full bg-border">
                        <div className="h-full w-1/5 rounded-full bg-foreground animate-stage-sweep" />
                      </div>
                      {stage.caption && (
                        <p className="text-sm text-muted-foreground">{stage.caption}</p>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>

        <p className="text-sm text-muted-foreground">
          This page updates on its own. You can leave it open.
        </p>
      </div>
    </div>
  );
}
