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
import { api, Job, Violation } from "@/lib/api";

function isProcessing(status: string): boolean {
  return !["completed", "failed"].includes(status);
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
  const [isExporting, setIsExporting] = useState(false);
  const [isCleaning, setIsCleaning] = useState(false);
  const [exportReady, setExportReady] = useState(false);

  const waveformRef = useRef<WaveformHandle>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

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

  useEffect(() => {
    if (!job || !isProcessing(job.status)) return;
    const interval = setInterval(async () => {
      try {
        const jobData = await api.getJob(jobId);
        setJob(jobData);
        if (jobData.status === "completed") {
          const vData = await api.getViolations(jobId);
          setViolations(vData);
          if (vData.length > 0) setSelectedViolation(vData[0]);
          clearInterval(interval);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
  }, [job?.status, jobId]);

  const handleStatusUpdate = async (status: "accepted" | "rejected") => {
    if (!selectedViolation) return;
    setIsUpdating(true);
    try {
      const updated = await api.updateViolation(jobId, selectedViolation.id, { status });
      setViolations(v => v.map(vi => vi.id === updated.id ? updated : vi));
      setSelectedViolation(updated);
      setExportReady(false);
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
      setExportReady(false);
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
      setExportReady(false);
    } catch {
      setError("Clean All failed");
    } finally {
      setIsCleaning(false);
    }
  };

  const handleExport = async () => {
    setIsExporting(true);
    try {
      // No action argument - the backend honors each violation's own cut/mute
      await api.exportAudio(jobId);
      setExportReady(true);
    } catch (err) {
      setError("Export failed");
    } finally {
      setIsExporting(false);
    }
  };

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
        <div className="flex items-center gap-3">
          {exportReady ? (
            <Button size="sm" onClick={() => window.open(api.getExportDownloadUrl(jobId))}>Download Master</Button>
          ) : (
            <Button size="sm" onClick={handleExport} disabled={isExporting || violations.filter(v => v.status === "accepted").length === 0}>
              {isExporting ? "Exporting..." : "Export Edited"}
            </Button>
          )}
        </div>
      </header>

      {job.error_message && (
        <div className="border-b border-amber-500/40 bg-amber-500/10 px-8 py-3 text-xs text-amber-900 dark:text-amber-200">
          <span className="font-bold uppercase tracking-wide">Partial analysis</span> — {job.error_message}
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
    </div>
  );
}
