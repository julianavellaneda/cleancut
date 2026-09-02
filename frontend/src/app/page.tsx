"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import { api, JobListItem, Preset } from "@/lib/api";
import { cn } from "@/lib/utils";

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
    const allowedExtensions = /\.(mp3|wav|m4a|flac|ogg|webm|aif|aiff|mp4|mov)$/i;
    const validFiles = files.filter(file => allowedExtensions.test(file.name));

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

  const activePreset = presets.find(p => p.id === preset) ?? null;

  return (
    <div className="container max-w-4xl mx-auto py-12 px-6 space-y-12">
      <header className="flex items-end justify-between gap-6">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">CleanCut</h1>
          <p className="text-muted-foreground">Describe what to find in plain English. Review it on a waveform. Export a surgically edited file.</p>
        </div>
        {/*
          The layout footer that used to carry the Admin link is gone with the
          redesign, so the link lives here. Phase 2 restyles this header; the
          route has to stay reachable in between.
        */}
        <div className="flex flex-none items-center gap-2">
          <a
            href="/admin"
            className="rounded-full px-3 py-1.5 text-sm text-muted-foreground no-underline transition-colors hover:bg-surface hover:text-foreground"
          >
            Maintenance
          </a>
          <ThemeToggle />
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Create New Edit</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="prompt" className="text-sm font-medium">
                Instructions {activePreset && <span className="text-xs font-normal text-muted-foreground">(disabled — {activePreset.name} preset active)</span>}
              </label>
              <textarea
                id="prompt"
                placeholder={activePreset ? `The ${activePreset.name} rulebook is driving this analysis.` : "E.g., Remove filler words and silences..."}
                value={activePreset ? "" : prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={!!activePreset}
                className={cn(
                  "w-full min-h-[100px] p-3 rounded-md border border-input bg-background text-sm focus:ring-1 focus:ring-primary outline-none transition-all",
                  activePreset && "opacity-50 cursor-not-allowed"
                )}
              />
            </div>

            {presets.length > 0 && (
              <div className="space-y-2">
                <label htmlFor="preset" className="text-sm font-medium">Rule preset</label>
                <select
                  id="preset"
                  value={preset ?? ""}
                  onChange={(e) => setPreset(e.target.value || null)}
                  className={cn(
                    "w-full p-3 rounded-md border bg-background text-sm focus:ring-1 focus:ring-primary outline-none transition-all",
                    activePreset ? "border-primary bg-primary/5" : "border-input"
                  )}
                >
                  <option value="">None — use my instructions</option>
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                {activePreset && (
                  <div className="text-xs text-muted-foreground px-1">
                    {activePreset.description} The custom prompt is ignored while a preset is selected.
                  </div>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <label className="flex items-center gap-3 p-3 border rounded-md cursor-pointer hover:bg-surface2/50 transition-colors">
                <input
                  type="checkbox"
                  checked={autoFix}
                  onChange={(e) => setAutoFix(e.target.checked)}
                  className="w-4 h-4 rounded border-input"
                />
                <span className="text-sm font-medium">Auto-apply markers</span>
              </label>
              <label className="flex items-center gap-3 p-3 border rounded-md cursor-pointer hover:bg-surface2/50 transition-colors">
                <input
                  type="checkbox"
                  checked={autoScrub}
                  onChange={(e) => setAutoScrub(e.target.checked)}
                  className="w-4 h-4 rounded border-input"
                />
                <span className="text-sm font-medium">Scrubber mode</span>
              </label>
            </div>
          </div>

          <div
            className={cn(
              "border-2 border-dashed rounded-lg p-12 text-center transition-all cursor-pointer",
              isDragging ? "border-primary bg-primary/5" : "border-muted-foreground/20 hover:border-muted-foreground/40",
              isUploading && "pointer-events-none opacity-50"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !isUploading && document.getElementById("file-input")?.click()}
          >
            <input id="file-input" type="file" multiple className="hidden" onChange={handleFileInput} />
            {isUploading ? (
              <div className="text-sm font-medium animate-pulse">Processing Upload...</div>
            ) : (
              <div className="space-y-1">
                <div className="text-sm font-medium">Drop media files here</div>
                <div className="text-xs text-muted-foreground">or click to browse local storage</div>
              </div>
            )}
          </div>
          {/* Per-file upload state. A multi-file drop is one request per file,
              so the blanket "Processing Upload..." above cannot say which ones
              landed, and `error` only ever holds the last failure. This was
              tracked but never rendered, which is why a partially failed drop
              read as a wholly failed one. */}
          {Object.keys(uploadProgress).length > 0 && (
            <ul className="space-y-1 text-xs">
              {Object.entries(uploadProgress).map(([name, state]) => (
                <li key={name} className="flex items-center justify-between gap-4">
                  <span className="truncate text-muted-foreground">{name}</span>
                  <span className={cn(
                    "font-semibold uppercase tracking-wider shrink-0",
                    state === "Failed" ? "text-destructive" : "text-muted-foreground"
                  )}>
                    {state}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {error && <div className="text-xs font-medium text-destructive text-center">{error}</div>}
        </CardContent>
      </Card>

      {jobs.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Recent Projects</h2>
            <Button variant="ghost" size="xs" onClick={loadJobs} disabled={loadingJobs} className="text-[10px]">
              {loadingJobs ? "REFRESHING..." : "REFRESH"}
            </Button>
          </div>
          <div className="grid gap-3">
            {jobs.map((job) => (
              <div key={job.id} className="flex items-center justify-between p-4 border rounded-lg bg-card shadow-sm hover:border-muted-foreground/30 transition-all">
                <div className="flex flex-col min-w-0 pr-4">
                  <div className="text-sm font-medium truncate">{job.original_filename || job.filename}</div>
                  <div className="text-[10px] text-muted-foreground uppercase font-semibold">
                    {formatDuration(job.duration_seconds)} — {job.status}
                  </div>
                </div>
                {job.status === "completed" ? (
                  <Button size="sm" onClick={() => router.push(`/jobs/${job.id}`)}>Review</Button>
                ) : (
                  <div className="text-[10px] font-bold text-muted-foreground uppercase animate-pulse">{job.status}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
