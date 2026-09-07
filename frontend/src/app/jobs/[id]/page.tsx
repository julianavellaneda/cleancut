"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import { ArrowLeftGlyph, DownloadGlyph } from "@/components/icons";
import { Waveform, WaveformHandle } from "@/components/Waveform";
import { ViolationList } from "@/components/ViolationList";
import { ExportPreview } from "@/components/ExportPreview";
import { ViolationCard } from "@/components/ViolationCard";
import { FailedView } from "@/components/FailedView";
import { ProcessingView } from "@/components/ProcessingView";
import { KeyboardLegend } from "@/components/KeyboardLegend";
import { ReanalyzeBar } from "@/components/ReanalyzeBar";
import { TranscriptPanel } from "@/components/TranscriptPanel";
import { api, ExportStatus, Job, Preset, Transcript, Violation } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { SCRUB_LABELS } from "@/lib/violations";
import { cn } from "@/lib/utils";

function isProcessing(status: string): boolean {
  return !["completed", "failed"].includes(status);
}

/** An export the worker has not finished with yet - keep polling. */
function isExportPending(status: ExportStatus | undefined): boolean {
  return status === "queued" || status === "exporting";
}

/**
 * Whether the rendered export predates the edit list on screen.
 *
 * Read off the job's revisions rather than remembered in component state: the
 * server retires a superseded export the moment an accepted edit moves, and a
 * flag living only in this component could not survive a reload, a second tab,
 * or the poll replacing the job object. A null `export_revision` is "provenance
 * unknown" - a job that never exported, or a row from before the columns - and
 * is deliberately not stale.
 */
function isExportStale(job: Job | null): boolean {
  if (!job || job.export_revision === null || job.export_revision === undefined) return false;
  return job.export_revision !== job.edit_revision;
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
  // The ids the last "Clean All" actually moved, so undo puts back that sweep
  // rather than every scrubber edit now sitting at accepted - one the reviewer
  // accepted by hand beforehand was never part of it. Cleared once undone.
  const [lastSweep, setLastSweep] = useState<string[] | null>(null);
  const [showReanalyze, setShowReanalyze] = useState(false);
  const [isReanalyzing, setIsReanalyzing] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  // Jobs processed before transcripts were persisted return null here, so the
  // panel is opt-in twice over: only shown when the user asks, and only when
  // this particular job actually has one.
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  // Fetched once for the whole screen: the header turns the job's preset id
  // into a name with it, and the re-analysis card offers the same list. A
  // failure leaves it empty, which degrades to the slug and to prompt mode
  // rather than to a blank screen.
  const [presets, setPresets] = useState<Preset[]>([]);

  const waveformRef = useRef<WaveformHandle>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  const jobStatus = job?.status;
  const exportStatus: ExportStatus = job?.export_status ?? "none";
  const exportStale = isExportStale(job);
  const exportReady = exportStatus === "ready" && !exportStale;
  const acceptedEdits = violations.filter(v => v.status === "accepted");
  const acceptedCount = acceptedEdits.length;
  // What the render actually shortened: only the accepted *cuts*. A mute keeps
  // the timeline, so counting it here would promise a file shorter than the one
  // the strip is playing.
  const secondsRemoved = acceptedEdits
    .filter(v => v.action !== "mute")
    .reduce((total, v) => total + (v.end_time - v.start_time), 0);
  // What a re-analysis would throw away: the accepted suggestions the *model*
  // made. The scrubber's are deterministic and survive a re-run, decisions
  // included, so counting them here would overstate the cost of the click.
  const acceptedModelCount = violations.filter(
    v => v.status === "accepted" && !(v.label && SCRUB_LABELS.includes(v.label))
  ).length;

  /**
   * Mirror the retirement the server just performed.
   *
   * A violation update answers with the violation, not the job, so rather than
   * spend a round trip re-reading the job after every keystroke the page applies
   * the same rule the backend does: a finished export is retired, an in-flight
   * one is left for the worker to resolve when it lands.
   */
  const markExportInvalidated = useCallback(() => {
    setJob(prev => {
      if (!prev || isExportPending(prev.export_status)) return prev;
      return { ...prev, export_status: "none", export_error: null, export_revision: null };
    });
  }, []);

  const loadData = useCallback(async () => {
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);
      if (jobData.status === "completed") {
        const violationsData = await api.getViolations(jobId);
        setViolations(violationsData);
        // Seeded through the functional form rather than by reading
        // `selectedViolation` here: closing over it would put it in this
        // callback's dependencies, and the effect below would then re-fetch the
        // job and the whole violation list every time the reviewer moved the
        // selection. The rule is the same one the poll applies - only seed when
        // nothing is selected yet.
        setSelectedViolation(prev => prev ?? violationsData[0] ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job");
    } finally {
      setIsLoading(false);
    }
  }, [jobId]);

  // Same rule, same reason as the home page's mount effect - and here there is
  // not even a synchronous setState to point at: `loadData` awaits before it
  // touches state at all. See the comment there.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    let cancelled = false;
    api.listPresets()
      .then(list => { if (!cancelled) setPresets(list); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  // Fetched separately from the job: it can be large, it never changes once the
  // job completes, and a job without one is a normal case rather than an error.
  useEffect(() => {
    if (job?.status !== "completed" || transcript) return;
    let cancelled = false;
    api.getTranscript(jobId)
      .then(t => { if (!cancelled) setTranscript(t); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [job?.status, jobId, transcript]);

  // One poll covers both halves of the pipeline: the processing stages, and the
  // export render, which now runs on the same worker queue instead of inline in
  // the request.
  // Reads the two statuses as extracted values rather than off `job`, so the
  // dependency list can name exactly what it re-arms on. Depending on the whole
  // object would restart the interval on every poll tick, since each response is
  // a new object even when nothing about it changed.
  useEffect(() => {
    if (!jobStatus) return;
    const watchingProcessing = isProcessing(jobStatus);
    const watchingExport = isExportPending(exportStatus);
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
          // A re-analysis deletes the suggestions it replaces, so a selection
          // pointing at one that is gone has to fall back rather than persist
          // as a card describing a row nobody can act on.
          setSelectedViolation(prev =>
            (prev && vData.some(v => v.id === prev.id) ? prev : vData[0]) ?? null
          );
        }
      } catch {}
    }, 2000);
    return () => clearInterval(interval);
  }, [jobStatus, exportStatus, jobId]);

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
      markExportInvalidated();
    } catch {
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
      markExportInvalidated();
    } catch {
      setError("Update failed");
    } finally {
      setIsUpdating(false);
    }
  };

  /** Re-read the list after a bulk move, keeping the selection where it was. */
  const refreshViolations = async () => {
    const refreshed = await api.getViolations(jobId);
    setViolations(refreshed);
    if (selectedViolation) {
      setSelectedViolation(
        refreshed.find(v => v.id === selectedViolation.id) ?? selectedViolation
      );
    }
    markExportInvalidated();
  };

  const handleCleanAll = async () => {
    setIsCleaning(true);
    try {
      // Captured before the call: after it, these rows are indistinguishable
      // from any scrubber edit that was already accepted.
      const swept = violations
        .filter(v => v.status === "pending" && v.label && SCRUB_LABELS.includes(v.label))
        .map(v => v.id);

      await api.bulkUpdateViolations(jobId, { status: "accepted" }, SCRUB_LABELS);
      await refreshViolations();
      setLastSweep(swept);
    } catch {
      setError("Clean All failed");
    } finally {
      setIsCleaning(false);
    }
  };

  const handleUndoCleanAll = async () => {
    if (!lastSweep) return;
    setIsCleaning(true);
    try {
      await api.bulkUpdateViolations(
        jobId, { status: "pending", ids: lastSweep }, undefined, ["accepted"]
      );
      await refreshViolations();
      setLastSweep(null);
    } catch {
      setError("Undo failed");
    } finally {
      setIsCleaning(false);
    }
  };

  const handleReanalyze = async (request: { prompt?: string; preset?: string }) => {
    setIsReanalyzing(true);
    setError(null);
    try {
      await api.reanalyzeJob(jobId, request);
      setShowReanalyze(false);
      setLastSweep(null);
      // The job comes back `analyzing`, which re-arms the poll and swaps in the
      // processing view; loadData would race it, so the local status is what
      // hands over.
      setJob(prev => (prev ? { ...prev, status: "analyzing", error_message: null } : prev));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-analysis failed");
    } finally {
      setIsReanalyzing(false);
    }
  };

  const handleExport = async () => {
    setError(null);
    try {
      // No action argument - the backend honors each violation's own cut/mute.
      // This returns as soon as the render is queued; the poll above watches
      // export_status from there.
      const queued = await api.exportAudio(jobId);
      // export_revision stays null until the render lands, which reads as
      // "nothing of known provenance yet" rather than as a stale file.
      setJob(prev => (prev
        ? { ...prev, export_status: queued.export_status, export_error: null, export_revision: null }
        : prev));
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

      // The transcript's lines are buttons; when one has focus, Space belongs to
      // the browser's activate-the-button default, not to the transport.
      if (e.key === " " && target?.tagName === "BUTTON") return;

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
      if (key === "t") {
        e.preventDefault();
        setShowTranscript(v => !v);
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
  if (job.status === "failed") return <FailedView job={job} />;

  const jobName = job.original_filename || job.filename;
  const activePreset = presets.find(p => p.id === job.preset) ?? null;
  const jobMeta = [
    job.media_type === "video" ? "Video" : "Audio",
    job.duration_seconds ? formatDuration(job.duration_seconds) : null,
    // An unfetched preset list falls back to the slug rather than to "Prompt
    // mode", which would misdescribe the job.
    job.preset ? `${activePreset?.name ?? job.preset} preset` : "Prompt mode",
  ].filter(Boolean).join(" · ");

  // A failed render owns the retry, and it lives in the banner that explains
  // the failure rather than in the header - so the header's export control is
  // whatever is left: the download once a current file exists, otherwise the
  // button that makes one.
  const exportFailed = exportStatus === "failed" && !exportStale;
  const exportLabel =
    exportStatus === "queued" ? "Queued…"
    : exportStatus === "exporting" ? "Exporting…"
    : acceptedCount > 0 ? `Export ${acceptedCount} edit${acceptedCount === 1 ? "" : "s"}`
    : "Export";

  /* The pills in the header's right cluster: one border, one toggling fill. */
  const chromePill = (active: boolean) => cn(
    "inline-flex items-center gap-1.5 rounded-full border border-divider px-3.5 py-2",
    "text-[13px] transition-colors hover:border-acc disabled:pointer-events-none disabled:opacity-50",
    active ? "bg-surface2 text-text" : "bg-transparent text-text"
  );

  return (
    <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-4 px-7 pt-5 pb-20">
      <header className="flex flex-wrap items-center gap-3.5">
        <Link
          href="/"
          title="All recordings"
          aria-label="All recordings"
          className="grid size-[38px] flex-none place-items-center rounded-full border border-divider text-text no-underline transition-colors hover:bg-surface"
        >
          <ArrowLeftGlyph size={16} />
        </Link>

        <div className="min-w-0 flex-1">
          <h1 className="truncate font-heading text-[22px] leading-[1.15]">{jobName}</h1>
          <div className="text-xs text-muted">{jobMeta}</div>
        </div>

        {/* The render happens on the worker queue, so the control reports the
            job's export_status rather than the lifetime of a hanging request. */}
        <div className="flex flex-wrap items-center gap-2">
          {transcript && (
            <button
              type="button"
              onClick={() => setShowTranscript(v => !v)}
              aria-pressed={showTranscript}
              className={chromePill(showTranscript)}
            >
              Transcript
              {/* Hidden from the accessible name: the shortcut is a hint for
                  people looking at the button, and "Transcript T" is not what
                  the button is called. */}
              <kbd aria-hidden className="rounded-[5px] bg-surface2 px-1.5 py-px font-mono text-[10px] font-semibold opacity-80">
                T
              </kbd>
            </button>
          )}
          {transcript && (
            <button
              type="button"
              onClick={() => setShowReanalyze(v => !v)}
              aria-pressed={showReanalyze}
              title="Ask a different question about this recording, without re-transcribing it"
              className={chromePill(showReanalyze)}
            >
              New prompt
            </button>
          )}

          <ThemeToggle />

          {exportReady ? (
            /* Blue rather than violet: the colour change is the signal that the
               artefact exists, and a real link is what lets the browser save it. */
            <a
              href={api.getExportDownloadUrl(jobId)}
              download
              className="inline-flex items-center gap-2 rounded-full bg-acc2 px-[18px] py-2.5 font-heading text-sm text-onacc no-underline transition-colors hover:bg-acc2-h hover:text-onacc"
            >
              <DownloadGlyph size={14} />
              Download edited file
            </a>
          ) : !exportFailed && (
            <Button
              onClick={handleExport}
              disabled={isExportPending(exportStatus) || acceptedCount === 0}
              title={acceptedCount === 0 ? "Accept at least one edit to export" : undefined}
            >
              {isExportPending(exportStatus) && (
                <span aria-hidden className="size-3 animate-cc-spin rounded-full border-2 border-onacc border-t-transparent" />
              )}
              {exportLabel}
            </Button>
          )}
        </div>
      </header>

      {exportFailed && (
        <div className="flex items-start gap-3.5 rounded-lg bg-danger-100 px-[18px] py-3 text-[13px] text-danger-700">
          <div className="min-w-0 flex-1">
            <strong className="font-bold">Export failed.</strong>{" "}
            <span className="break-words font-mono text-xs">{job.export_error ?? "unknown error"}</span>
          </div>
          <button
            type="button"
            onClick={handleExport}
            className="flex-none rounded-full border border-current px-3 py-1 text-xs transition-opacity hover:opacity-80"
          >
            Retry export
          </button>
        </div>
      )}

      {/* Set by a failed update or a rejected export. Previously assigned and
          never rendered, so an export the server refused looked like nothing
          had happened at all. */}
      {error && (
        <div className="flex items-start gap-3.5 rounded-lg bg-danger-100 px-[18px] py-3 text-[13px] text-danger-700">
          <span className="flex-1 break-words">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            aria-label="Dismiss"
            className="px-1 text-base leading-none"
          >
            ×
          </button>
        </div>
      )}

      {/* A completed job can still carry a warning: a partial analysis, or a
          skipped dead-air pass. The backend message names its own case
          ("Partial analysis: ...", "Dead air detection skipped: ..."), so the
          label here stays generic rather than mislabelling one as the other. */}
      {job.error_message && (
        <div className="flex items-start gap-3 rounded-lg bg-acc2-100 px-[18px] py-3 text-[13px] text-acc2-700">
          <span className="flex-none pt-0.5 text-[11px] font-bold uppercase tracking-[0.06em]">Heads up</span>
          <span className="flex-1 text-pretty">{job.error_message}</span>
        </div>
      )}

      {showReanalyze && (
        <ReanalyzeBar
          currentPrompt={job.prompt}
          currentPreset={job.preset}
          presets={presets}
          acceptedModelCount={acceptedModelCount}
          isSubmitting={isReanalyzing}
          onSubmit={handleReanalyze}
          onCancel={() => setShowReanalyze(false)}
        />
      )}

      <div className="review-grid" data-transcript={transcript && showTranscript ? "open" : "closed"}>
        <section className="review-list rounded-2xl bg-surface">
          <ViolationList violations={violations} selectedViolation={selectedViolation} onSelect={setSelectedViolation} onCleanAll={handleCleanAll} onUndoCleanAll={handleUndoCleanAll}
            canUndoCleanAll={lastSweep !== null && lastSweep.length > 0} isCleaning={isCleaning} />
        </section>

        <section className="review-media flex min-w-0 flex-col gap-3">
          {job.media_type === "video" && (
            <video ref={videoRef} src={api.getAudioUrl(jobId)} className="max-h-[360px] w-full rounded-lg bg-black" controls />
          )}

          <div className="rounded-2xl bg-surface px-[18px] pt-4 pb-3.5">
            <Waveform ref={waveformRef} audioUrl={api.getAudioUrl(jobId)} violations={violations} selectedViolation={selectedViolation} onViolationClick={setSelectedViolation} onTimeUpdate={setCurrentTime} mediaRef={job.media_type === "video" ? videoRef : undefined} />
          </div>

          {exportReady && (
            job.media_type === "video" ? (
              <div className="rounded-lg bg-acc2-100 px-[18px] py-3.5 text-acc2-700">
                <div className="mb-2 text-sm font-semibold">Edited result</div>
                {/*
                  A video export keeps the browser's own controls: the audio
                  strip below is a transport with no picture, and a render whose
                  point is the picture needs one.
                */}
                <video src={api.getExportStreamUrl(jobId)} className="w-full rounded-md bg-black" controls />
              </div>
            ) : (
              <ExportPreview
                src={api.getExportStreamUrl(jobId)}
                editCount={acceptedEdits.length}
                secondsRemoved={secondsRemoved}
              />
            )
          )}
        </section>

        <section className="review-detail min-w-0 rounded-2xl bg-surface px-[22px] pt-5 pb-4.5">
          {selectedViolation ? (
            <ViolationCard violation={selectedViolation} index={selectedIndex + 1} total={violations.length} onAccept={() => handleStatusUpdate("accepted")} onReject={() => handleStatusUpdate("rejected")} onActionChange={handleActionChange} onPlayClip={() => waveformRef.current?.playClip(selectedViolation.start_time, selectedViolation.end_time)} isUpdating={isUpdating} />
          ) : (
            <div className="py-12 text-center text-sm text-muted text-pretty">
              {violations.length === 0
                ? "Nothing to review — the analysis found no matches for this instruction. You can ask a new question with New prompt."
                : "Select an edit to review"}
            </div>
          )}
        </section>

        {transcript && showTranscript && (
          <section className="review-transcript min-w-0 rounded-2xl bg-surface">
            <TranscriptPanel
              segments={transcript.segments}
              violations={violations}
              currentTime={currentTime}
              onSeek={(time) => waveformRef.current?.seekTo(time)}
            />
          </section>
        )}
      </div>

      <KeyboardLegend open={showLegend} onToggle={() => setShowLegend(v => !v)} />
    </div>
  );
}
