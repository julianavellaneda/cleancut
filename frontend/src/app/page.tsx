"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { CleanCutMark } from "@/components/CleanCutMark";
import { PresetRadioGroup } from "@/components/PresetRadioGroup";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ToggleSwitch } from "@/components/ToggleSwitch";
import { AudioGlyph, RefreshGlyph, UploadGlyph, VideoGlyph } from "@/components/icons";
import { api, JobListItem, Preset } from "@/lib/api";
import { cn } from "@/lib/utils";

/** The extensions the backend accepts, and the list the drop zone advertises. */
const ACCEPTED_EXTENSIONS = /\.(mp3|wav|m4a|flac|ogg|webm|aif|aiff|mp4|mov)$/i;
const ACCEPTED_LABEL = "mp3 · wav · m4a · flac · ogg · webm · aif · aiff · mp4 · mov";

/**
 * A job is either finished, finished badly, or still moving. The pill's colour
 * says which, and the pulse says the page is going to change on its own.
 */
function statusTone(status: string): string {
  if (status === "completed") return "bg-acc2-200 text-acc2-700";
  if (status === "failed") return "bg-danger-100 text-danger-700";
  return "bg-acc-200 text-acc-700 animate-cc-pulse";
}

export default function UploadPage() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [autoFix, setAutoFix] = useState(false);
  const [autoScrub, setAutoScrub] = useState(false);
  const [preset, setPreset] = useState<string | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ [key: string]: string }>({});
  const [isPolling, setIsPolling] = useState(false);

  const pollInterval = useRef<NodeJS.Timeout | null>(null);

  // These four *are* memoized, unlike the handlers further down, and the
  // difference is what they close over: nothing reactive. Between them they
  // touch the poll ref, the API client and four setters, all of which React
  // guarantees stable, so a `useCallback` with these dependencies is honest
  // rather than a frozen first-render closure - and it is what lets the mount
  // effect below list what it calls instead of claiming to depend on nothing.
  // Anything reading `prompt`, `preset`, `autoFix` or `autoScrub` belongs with
  // the un-memoized handlers, not here. See the note above `handleDragOver`.
  const stopPolling = useCallback(() => {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
    }
    setIsPolling(false);
  }, []);

  // The timer asks only about jobs still being worked on, and merges what comes
  // back into the cards already on screen. It used to re-fetch the whole job
  // list every three seconds - filename, prompt, preset and timestamps for
  // every job in the entire history - to notice that one of them had changed
  // stage. None of those fields move while a job runs, and with retention off
  // by default the history only grows.
  //
  // `setJobs` takes the functional form, so this callback still closes over
  // nothing reactive and the `[stopPolling]` dependency list stays honest.
  const startPolling = useCallback(() => {
    if (pollInterval.current) return;
    setIsPolling(true);
    pollInterval.current = setInterval(async () => {
      try {
        const active = await api.listActiveJobs();
        if (active.length === 0) {
          stopPolling();
          // One last full read, so a job that finished between two ticks
          // arrives with its final status and count rather than sitting on
          // screen as "analyzing" until the page is reloaded.
          setJobs(await api.listJobs());
          return;
        }
        const byId = new Map(active.map(job => [job.id, job]));
        setJobs(previous =>
          previous.map(job => {
            const update = byId.get(job.id);
            return update
              ? { ...job, status: update.status, violation_count: update.violation_count }
              : job;
          }),
        );
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 3000);
  }, [stopPolling]);

  const loadPresets = useCallback(async () => {
    try {
      setPresets(await api.listPresets());
    } catch {
      // Presets are optional - fall back to prompt-only mode.
    }
  }, []);

  const loadJobs = useCallback(async () => {
    setLoadingJobs(true);
    try {
      const jobList = await api.listJobs();
      setJobs(jobList);
      const hasActiveJobs = jobList.some(j => !["completed", "failed"].includes(j.status));
      if (hasActiveJobs) startPolling();
    } catch {
      // Ignore errors loading jobs
    } finally {
      setLoadingJobs(false);
    }
  }, [startPolling]);

  useEffect(() => {
    loadJobs();
    loadPresets();
    startPolling();
    return () => stopPolling();
  }, [loadJobs, loadPresets, startPolling, stopPolling]);

  // None of these are memoized, deliberately. They are handed to plain DOM
  // elements, so a stable identity buys no re-render that React was not going
  // to do anyway - and the empty dependency list it needs is a trap here: the
  // two that reach `handleFiles` used to be `useCallback(..., [])`, which froze
  // them around the *first* render's closure. `handleFiles` reads prompt,
  // preset, autoFix and autoScrub, so every upload shipped the initial values
  // and the settings above the drop zone did nothing at all.
  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) handleFiles(files);
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length > 0) handleFiles(files);
  }

  async function handleFiles(files: File[]) {
    const validFiles = files.filter(file => ACCEPTED_EXTENSIONS.test(file.name));

    if (validFiles.length === 0) {
      setError("Invalid file format.");
      return;
    }

    setError(null);
    setIsUploading(true);

    for (const file of validFiles) {
      setUploadProgress(prev => ({ ...prev, [file.name]: "Uploading..." }));
      try {
        await api.uploadAudio(file, prompt, autoFix, autoScrub, preset);
        setUploadProgress(prev => ({ ...prev, [file.name]: "Queued" }));
      } catch (err) {
        setUploadProgress(prev => ({ ...prev, [file.name]: "Failed" }));
        setError(err instanceof Error ? err.message : "Upload failed");
      }
    }

    setIsUploading(false);
    loadJobs();
    startPolling();
    setTimeout(() => setUploadProgress({}), 5000);
  }

  function formatDuration(seconds: number | null): string {
    if (seconds === null) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  /**
   * What drove the analysis, in the words the picker used. The job carries the
   * preset's *id*, so printing it raw would put a slug on screen next to
   * names everywhere else; the id is the fallback only when the preset list
   * has not arrived or no longer contains it.
   */
  function describeMode(job: JobListItem): string {
    if (!job.preset) return "prompt";
    const named = presets.find(p => p.id === job.preset);
    return `${named ? named.name : job.preset} preset`;
  }

  const activePreset = presets.find(p => p.id === preset) ?? null;

  return (
    <div className="mx-auto flex w-full max-w-[920px] flex-col gap-11 px-8 pt-14 pb-20">
      <header className="flex items-end justify-between gap-6">
        <div>
          <div className="mb-2.5 flex items-center gap-3">
            <CleanCutMark size={34} />
            <h1 className="font-heading text-[38px] leading-none tracking-[-0.015em]">CleanCut</h1>
          </div>
          <p className="max-w-[52ch] text-base text-muted text-pretty">
            Describe what to find in plain English. Review every proposed edit on the waveform.
            Nothing is removed until you say so.
          </p>
        </div>
        <div className="flex flex-none items-center gap-2">
          <a
            href="/admin"
            className="rounded-full px-2.5 py-1.5 text-[13px] text-muted no-underline transition-colors hover:bg-surface hover:text-text"
          >
            Maintenance
          </a>
          <ThemeToggle />
        </div>
      </header>

      <section className="flex flex-col gap-6 rounded-2xl bg-surface px-7 pt-7 pb-6">
        <h2 className="font-heading text-2xl leading-tight">New edit</h2>

        <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-[1.4fr_1fr]">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="prompt" className="flex justify-between text-xs text-muted">
              <span>Instructions</span>
              {activePreset && <span className="text-acc2-700">preset is driving the analysis</span>}
            </label>
            <div className="relative">
              <textarea
                id="prompt"
                placeholder="e.g. Remove filler words and long silences, and flag every income claim"
                value={activePreset ? "" : prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={!!activePreset}
                className="min-h-[120px] w-full resize-y rounded-[20px] border border-divider bg-bg px-4 py-3 text-sm leading-normal caret-acc outline-none transition-colors focus:border-acc"
              />
              {/*
                An overlay rather than the old 50% dim. Dimming says the control
                is unavailable; it does not say *why*, and the reason is the one
                thing the reviewer needs in order to get the textarea back.
              */}
              {activePreset && (
                <div className="absolute inset-0 flex items-center justify-center rounded-[20px] bg-bg/[0.92] p-4 text-center text-[13px] text-muted text-pretty">
                  <span>
                    The <strong className="font-semibold text-acc2-700">{activePreset.name}</strong>{" "}
                    rulebook is driving this analysis. Your instructions are ignored while it&apos;s
                    selected.
                  </span>
                </div>
              )}
            </div>
          </div>

          {presets.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <PresetRadioGroup presets={presets} value={preset} onChange={setPreset} />
              {activePreset && (
                <p className="mt-0.5 ml-1.5 text-xs text-muted text-pretty">
                  {activePreset.description}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {/*
            The descriptions are the mockup's, verbatim, and they are not
            decoration: "Uncertain ones stay pending" is the contract
            `worker._is_pre_accepted` actually implements, and it was nowhere on
            this screen before.
          */}
          <ToggleSwitch
            checked={autoFix}
            onChange={setAutoFix}
            title="Auto-apply markers"
            description="Pre-accept the model's suggestions and render the export right after analysis. Uncertain ones stay pending."
          />
          <ToggleSwitch
            checked={autoScrub}
            onChange={setAutoScrub}
            title="Scrubber mode"
            description="Pre-accept detected filler words and dead air. Uncertain ones stay pending."
          />
        </div>

        <div
          className={cn(
            "flex cursor-pointer flex-col items-center gap-1.5 rounded-[26px] border-2 border-dashed px-6 py-8 text-center transition-colors",
            isDragging ? "border-acc bg-acc-100" : "border-divider bg-transparent hover:border-acc",
            isUploading && "pointer-events-none opacity-50"
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !isUploading && document.getElementById("file-input")?.click()}
        >
          <input id="file-input" type="file" multiple className="hidden" onChange={handleFileInput} />
          <div className="mb-1 grid size-11 place-items-center rounded-full bg-acc-200 text-acc-700">
            <UploadGlyph size={20} />
          </div>
          <div className="text-[15px] font-semibold">
            {isUploading ? "Uploading…" : "Drop recordings here, or click to browse"}
          </div>
          <div className="text-xs text-muted">{ACCEPTED_LABEL} — several at once is fine</div>
        </div>

        {/* Per-file upload state. A multi-file drop is one request per file,
            so the blanket upload label above cannot say which ones landed, and
            `error` only ever holds the last failure. This was tracked but never
            rendered, which is why a partially failed drop read as a wholly
            failed one. */}
        {Object.keys(uploadProgress).length > 0 && (
          <ul className="-mt-2 flex flex-col gap-1.5 px-2 text-[13px]">
            {Object.entries(uploadProgress).map(([name, state]) => (
              <li key={name} className="flex items-center justify-between gap-4">
                <span className="truncate text-muted">{name}</span>
                <span
                  className={cn(
                    "flex-none rounded-full px-2.5 py-0.5 text-[11px] uppercase tracking-[0.08em]",
                    state === "Failed" ? "bg-danger-100 text-danger-700" : "bg-surface2 text-muted"
                  )}
                >
                  {state}
                </span>
              </li>
            ))}
          </ul>
        )}

        {error && (
          <div className="flex items-start gap-2.5 rounded-md bg-danger-100 px-4 py-2.5 text-[13px] text-danger-700 text-pretty">
            <span className="flex-none font-bold">!</span>
            <span className="flex-1">{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              aria-label="Dismiss error"
              className="cursor-pointer px-1 text-sm leading-none"
            >
              ×
            </button>
          </div>
        )}
      </section>

      {jobs.length > 0 && (
        <section className="flex flex-col gap-3.5">
          <div className="flex items-baseline gap-4">
            <h2 className="font-heading text-2xl leading-tight">Recordings</h2>
            {isPolling && (
              <span className="inline-flex items-center gap-1.5 text-xs text-muted">
                <span className="size-[7px] rounded-full bg-acc animate-cc-pulse" />
                updating every 3s
              </span>
            )}
            <Button
              variant="outline"
              size="pill-sm"
              onClick={loadJobs}
              disabled={loadingJobs}
              className="ml-auto"
            >
              <RefreshGlyph size={13} className={cn(loadingJobs && "animate-cc-spin")} />
              {loadingJobs ? "Refreshing…" : "Refresh"}
            </Button>
          </div>

          <div className="flex flex-col gap-2">
            {jobs.map((job) => {
              const isCompleted = job.status === "completed";
              const isFailed = job.status === "failed";

              return (
                <div
                  key={job.id}
                  className="grid grid-cols-[44px_1fr_auto_auto] items-center gap-4 rounded-lg bg-surface py-3 pr-4 pl-3"
                >
                  <div
                    className={cn(
                      "grid size-11 place-items-center rounded-full",
                      isFailed ? "bg-danger-100 text-danger-700" : "bg-acc-200 text-acc-700"
                    )}
                  >
                    {job.media_type === "video" ? <VideoGlyph /> : <AudioGlyph />}
                  </div>

                  <div className="min-w-0">
                    <div className="truncate text-[15px] font-semibold">
                      {job.original_filename || job.filename}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      <span>{formatDuration(job.duration_seconds)}</span>
                      <span className="opacity-50">·</span>
                      <span>{describeMode(job)}</span>
                      {job.violation_count > 0 && (
                        <>
                          <span className="opacity-50">·</span>
                          <span>{job.violation_count} suggestions</span>
                        </>
                      )}
                    </div>
                  </div>

                  <span
                    className={cn(
                      "rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.08em]",
                      statusTone(job.status)
                    )}
                  >
                    {job.status}
                  </span>

                  {isCompleted ? (
                    <Button size="sm" onClick={() => router.push(`/jobs/${job.id}`)}>
                      Review
                    </Button>
                  ) : isFailed ? (
                    <Button
                      variant="outline"
                      size="pill-sm"
                      onClick={() => router.push(`/jobs/${job.id}`)}
                    >
                      Details
                    </Button>
                  ) : (
                    // Holds the column open, so a list of jobs at different
                    // stages does not have its status pills jumping sideways.
                    <span className="w-[76px]" />
                  )}
                </div>
              );
            })}
          </div>

          <div className="px-2 py-1 text-xs text-faint">
            Showing {jobs.length} of {jobs.length} · newest first
          </div>
        </section>
      )}
    </div>
  );
}
