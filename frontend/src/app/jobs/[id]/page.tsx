"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Waveform, WaveformHandle } from "@/components/Waveform";
import { ViolationList, SCRUB_LABELS } from "@/components/ViolationList";
import { ViolationCard } from "@/components/ViolationCard";
import { ProcessingView } from "@/components/ProcessingView";
import { KeyboardLegend } from "@/components/KeyboardLegend";
import { api, ExportStatus, Job, Violation } from "@/lib/api";

function isProcessing(status: string): boolean {
  return !["completed", "failed"].includes(status);
}

/** An export the worker has not finished with yet - keep polling. */
function isExportPending(status: ExportStatus | undefined): boolean {
  return status === "queued" || status === "exporting";
}

export default function ReviewPage() {
  const params = useParams();
  const jobId = params.id as string;

  const [job, setJob] = useState<Job | null>(null);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [selectedViolation, setSelectedViolation] = useState<Violation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);
  // The edit set changed since the last render, so whatever sits in exports/ is
  // stale. Tracked separately from the server's export_status, which describes
  // the last render rather than whether it still matches the review.
  const [exportStale, setExportStale] = useState(false);
  const [showLegend, setShowLegend] = useState(false);

  const waveformRef = useRef<WaveformHandle>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const exportStatus: ExportStatus = job?.export_status ?? "none";
  const exportReady = exportStatus === "ready" && !exportStale;
  const acceptedCount = violations.filter(v => v.status === "accepted").length;

  const loadData = useCallback(async () => {
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);
      if (jobData.status === "completed") {
        const violationsData = await api.getViolations(jobId);
        setViolations(violationsData);
        if (violationsData.length > 0 && !selectedViolation) setSelectedViolation(violationsData[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job");
    } finally {
      setIsLoading(false);
    }
  }, [jobId, selectedViolation]);

  useEffect(() => { loadData(); }, [jobId]);

  // One poll covers both halves of the pipeline: the processing stages, and the
  // export render, which now runs on the same worker queue instead of inline in
  // the request.
  useEffect(() => {
    if (!job) return;
    const watchingProcessing = isProcessing(job.status);
    const watchingExport = isExportPending(job.export_status);
    if (!watchingProcessing && !watchingExport) return;

    const interval = setInterval(async () => {
      try {
        const jobData = await api.getJob(jobId);
        setJob(jobData);
        if (watchingProcessing && jobData.status === "completed") {
          const vData = await api.getViolations(jobId);
          setViolations(vData);
          // Only seed the selection when there isn't one. Without this guard
          // the poll yanked the user back to the first suggestion on every tick.
          setSelectedViolation(prev => prev ?? vData[0] ?? null);
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [job?.status, job?.export_status, jobId]);

  const handleStatusUpdate = async (
    status: "accepted" | "rejected",
    { advance = false }: { advance?: boolean } = {}
  ) => {
    if (!selectedViolation) return;
    setIsUpdating(true);
    try {
      const updated = await api.updateViolation(jobId, selectedViolation.id, { status });
      setViolations(v => v.map(vi => vi.id === updated.id ? updated : vi));
      // Deciding from the keyboard moves on to the next suggestion; deciding
      // from the buttons leaves the reviewer where they clicked.
      const index = violations.findIndex(vi => vi.id === updated.id);
      setSelectedViolation(advance ? violations[index + 1] ?? updated : updated);
      setExportStale(true);
    } catch (err) {
      setError("Update failed");
    } finally {
      setIsUpdating(false);
    }
  };

  const handleActionChange = async (action: "cut" | "mute") => {
    if (!selectedViolation || selectedViolation.action === action) return;
    setIsUpdating(true);
    try {
      const updated = await api.updateViolation(jobId, selectedViolation.id, { action });
      setViolations(v => v.map(vi => vi.id === updated.id ? updated : vi));
      setSelectedViolation(updated);
      setExportStale(true);
    } catch {
      setError("Update failed");
    } finally {
      setIsUpdating(false);
    }
  };

  const handleCleanAll = async () => {
    setIsCleaning(true);
    try {
      await api.bulkUpdateViolations(jobId, { status: "accepted" }, SCRUB_LABELS);
      const refreshed = await api.getViolations(jobId);
      setViolations(refreshed);
      if (selectedViolation) {
        setSelectedViolation(
          refreshed.find(v => v.id === selectedViolation.id) ?? selectedViolation
        );
      }
      setExportStale(true);
    } catch {
      setError("Clean All failed");
    } finally {
      setIsCleaning(false);
    }
  };

  const handleExport = async () => {
    setError(null);
    try {
      // No action argument - the backend honors each violation's own cut/mute.
      // This returns as soon as the render is queued; the poll above watches
      // export_status from there.
      const queued = await api.exportAudio(jobId);
      setExportStale(false);
      setJob(prev => (prev ? { ...prev, export_status: queued.export_status, export_error: null } : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    }
  };

  const selectedIndex = selectedViolation
    ? violations.findIndex(v => v.id === selectedViolation.id)
    : -1;

  const selectAt = useCallback((index: number) => {
    if (violations.length === 0) return;
    const clamped = Math.max(0, Math.min(violations.length - 1, index));
    setSelectedViolation(violations[clamped]);
  }, [violations]);

  const playSelectedClip = useCallback(() => {
    if (!selectedViolation) return;
    waveformRef.current?.playClip(selectedViolation.start_time, selectedViolation.end_time);
  }, [selectedViolation]);

  // Keyboard review. Reviewing eighty filler words by mouse is the actual
  // bottleneck in this UI, so A/R advance to the next suggestion rather than
  // leaving the reviewer to click back into the list each time.
  useEffect(() => {
    if (!job || job.status !== "completed") return;

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) {
        return;
      }

      const key = e.key.toLowerCase();

      // Navigation stays live during an in-flight update; the decision keys do
      // not, so a held-down "a" cannot stack overlapping PATCHes.
      if (key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        selectAt(selectedIndex + 1);
        return;
      }
      if (key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        selectAt(selectedIndex - 1);
        return;
      }
      if (key === "?") {
        e.preventDefault();
        setShowLegend(v => !v);
        return;
      }
      if (e.key === " ") {
        e.preventDefault();
        waveformRef.current?.togglePlayPause();
        return;
      }
      if (key === "p") {
        e.preventDefault();
        playSelectedClip();
        return;
      }

      if (isUpdating || !selectedViolation) return;

      if (key === "a") {
        e.preventDefault();
        void handleStatusUpdate("accepted", { advance: true });
        return;
      }
      if (key === "r") {
        e.preventDefault();
        void handleStatusUpdate("rejected", { advance: true });
        return;
      }
      if (key === "m") {
        e.preventDefault();
        void handleActionChange(selectedViolation.action === "mute" ? "cut" : "mute");
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // handleStatusUpdate/handleActionChange are re-created every render and close
    // over jobId, violations and selectedViolation - all of which are listed
    // here, so the bound handler is never stale.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, violations, selectedViolation, selectedIndex, isUpdating, selectAt, playSelectedClip]);

  if (isLoading) return <div className="h-screen flex items-center justify-center text-sm text-muted-foreground">Loading…</div>;
  if (!job) return <div className="h-screen flex items-center justify-center"><Link href="/"><Button>Back to Home</Button></Link></div>;

  // While the worker is on the job there is nothing to review: no violations,
  // and a waveform pointed at a file that has not been processed. Show the
  // pipeline instead. `isProcessing` already drives the poll above; this is the
  // rendering half it was missing.
  if (isProcessing(job.status)) return <ProcessingView job={job} />;

  // A failed job has no violations and no waveform worth showing. Render the
  // reason instead of an empty review UI, which otherwise looks like a clean
  // recording rather than a job that never ran.
  if (job.status === "failed") {
    return (
      <div className="h-screen flex flex-col items-center justify-center gap-4 px-8 text-center">
        <h1 className="text-lg font-bold tracking-tight">Processing failed</h1>
        <p className="text-sm text-muted-foreground max-w-xl">
          {job.original_filename || job.filename} could not be processed.
        </p>
        {job.error_message && (
          <pre className="max-w-2xl w-full overflow-auto rounded-lg border bg-muted/40 p-4 text-left text-xs whitespace-pre-wrap">
            {job.error_message}
          </pre>
        )}
        <Link href="/"><Button size="sm">Back to Projects</Button></Link>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background">
      <header className="border-b px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/" className="text-sm font-medium hover:underline transition-all">← Projects</Link>
          <h1 className="text-lg font-bold tracking-tight truncate max-w-md">{job.original_filename || job.filename}</h1>
        </div>
        {/* The render happens on the worker queue, so the button reports the
            job's export_status rather than the lifetime of a hanging request. */}
        <div className="flex items-center gap-3">
          {exportStatus === "failed" && !exportStale && (
            <span className="max-w-xs truncate text-xs text-destructive" title={job.export_error ?? undefined}>
              Export failed: {job.export_error ?? "unknown error"}
            </span>
          )}
          {exportReady ? (
            <Button size="sm" onClick={() => window.open(api.getExportDownloadUrl(jobId))}>Download Master</Button>
          ) : (
            <Button
              size="sm"
              onClick={handleExport}
              disabled={isExportPending(exportStatus) || acceptedCount === 0}
            >
              {exportStatus === "queued" ? "Queued…"
                : exportStatus === "exporting" ? "Exporting…"
                : exportStatus === "failed" && !exportStale ? "Retry Export"
                : "Export Edited"}
            </Button>
          )}
        </div>
      </header>

      {/* Set by a failed update or a rejected export. Previously assigned and
          never rendered, so an export the server refused looked like nothing
          had happened at all. */}
      {error && (
        <div className="border-b border-destructive/40 bg-destructive/10 px-8 py-3 text-xs text-destructive">
          {error}
          <button
            type="button"
            onClick={() => setError(null)}
            className="ml-3 underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* A completed job can still carry a warning: a partial analysis, or a
          skipped dead-air pass. The backend message names its own case
          ("Partial analysis: ...", "Dead air detection skipped: ..."), so the
          label here stays generic rather than mislabelling one as the other. */}
      {job.error_message && (
        <div className="border-b border-amber-500/40 bg-amber-500/10 px-8 py-3 text-xs text-amber-900 dark:text-amber-200">
          <span className="font-bold uppercase tracking-wide">Heads up</span> — {job.error_message}
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        <aside className="w-80 border-r bg-muted/20">
          <ViolationList violations={violations} selectedViolation={selectedViolation} onSelect={setSelectedViolation} onCleanAll={handleCleanAll} isCleaning={isCleaning} />
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden">
          <div className="p-8 border-b bg-muted/10">
            <div className="max-w-4xl mx-auto w-full">
              {job.media_type === "video" && (
                <video ref={videoRef} src={api.getAudioUrl(jobId)} className="w-full aspect-video rounded-lg border mb-8 bg-black" controls />
              )}
              <Waveform ref={waveformRef} audioUrl={api.getAudioUrl(jobId)} violations={violations} selectedViolation={selectedViolation} onViolationClick={setSelectedViolation} mediaRef={job.media_type === "video" ? videoRef : undefined} />

              {exportReady && (
                <div className="mt-8 rounded-lg border bg-background p-4">
                  <div className="mb-3 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Result</div>
                  {job.media_type === "video" ? (
                    <video src={api.getExportStreamUrl(jobId)} className="w-full aspect-video rounded-md border bg-black" controls />
                  ) : (
                    <audio src={api.getExportStreamUrl(jobId)} className="w-full" controls />
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 p-8 overflow-auto">
            <div className="max-w-2xl mx-auto">
              {selectedViolation ? (
                <ViolationCard violation={selectedViolation} onAccept={() => handleStatusUpdate("accepted")} onReject={() => handleStatusUpdate("rejected")} onActionChange={handleActionChange} onPlayClip={() => waveformRef.current?.playClip(selectedViolation.start_time, selectedViolation.end_time)} isUpdating={isUpdating} />
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
                  {violations.length === 0 ? "No edits suggested for this recording" : "Select an edit to review"}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>

      <KeyboardLegend open={showLegend} onToggle={() => setShowLegend(v => !v)} />
    </div>
  );
}
