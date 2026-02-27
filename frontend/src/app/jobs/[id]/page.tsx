"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Waveform, WaveformHandle } from "@/components/Waveform";
import { ViolationList } from "@/components/ViolationList";
import { ViolationCard } from "@/components/ViolationCard";
import { api, Job, Violation } from "@/lib/api";

type ProcessingStatus = "pending" | "transcribing" | "analyzing" | "completed" | "failed";

const PROCESSING_STEPS: { key: ProcessingStatus; label: string }[] = [
  { key: "pending", label: "Upload" },
  { key: "transcribing", label: "Transcribing" },
  { key: "analyzing", label: "Analyzing" },
  { key: "completed", label: "Complete" },
];

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
  const [exportReady, setExportReady] = useState(false);

  const waveformRef = useRef<WaveformHandle>(null);

  // Load job data (and violations if completed)
  const loadData = useCallback(async () => {
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);

      if (jobData.status === "completed") {
        const violationsData = await api.getViolations(jobId);
        setViolations(violationsData);
        if (violationsData.length > 0 && !selectedViolation) {
          setSelectedViolation(violationsData[0]);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job");
    } finally {
      setIsLoading(false);
    }
  }, [jobId, selectedViolation]);

  // Initial load
  useEffect(() => {
    loadData();
  }, [jobId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while processing
  useEffect(() => {
    if (!job || !isProcessing(job.status)) return;

    const interval = setInterval(async () => {
      try {
        const jobData = await api.getJob(jobId);
        setJob(jobData);

        if (jobData.status === "completed") {
          const violationsData = await api.getViolations(jobId);
          setViolations(violationsData);
          if (violationsData.length > 0) {
            setSelectedViolation(violationsData[0]);
          }
          clearInterval(interval);
        } else if (jobData.status === "failed") {
          clearInterval(interval);
        }
      } catch {
        // Ignore polling errors, will retry
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [job?.status, jobId]);

  const handleViolationSelect = useCallback((violation: Violation) => {
    setSelectedViolation(violation);
  }, []);

  const handleStatusUpdate = useCallback(
    async (status: "accepted" | "rejected") => {
      if (!selectedViolation) return;

      setIsUpdating(true);
      try {
        const updated = await api.updateViolation(
          jobId,
          selectedViolation.id,
          { status }
        );

        setViolations((prev) =>
          prev.map((v) => (v.id === updated.id ? updated : v))
        );
        setSelectedViolation(updated);

        const jobData = await api.getJob(jobId);
        setJob(jobData);

        setExportReady(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update");
      } finally {
        setIsUpdating(false);
      }
    },
    [jobId, selectedViolation]
  );

  const handleBulkUpdate = useCallback(
    async (status: "accepted" | "rejected") => {
      setIsUpdating(true);
      try {
        await api.bulkUpdateViolations(jobId, { status });

        // Refresh violations and job
        const [jobData, violationsData] = await Promise.all([
          api.getJob(jobId),
          api.getViolations(jobId),
        ]);
        setJob(jobData);
        setViolations(violationsData);

        // Update selected violation from refreshed data
        if (selectedViolation) {
          const updated = violationsData.find((v) => v.id === selectedViolation.id);
          if (updated) setSelectedViolation(updated);
        }

        setExportReady(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Bulk update failed");
      } finally {
        setIsUpdating(false);
      }
    },
    [jobId, selectedViolation]
  );

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    try {
      await api.exportAudio(jobId, "cut");
      setExportReady(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setIsExporting(false);
    }
  }, [jobId]);

  const handleDownload = useCallback(() => {
    window.open(api.getExportDownloadUrl(jobId), "_blank");
  }, [jobId]);

  const playClip = useCallback(() => {
    if (!selectedViolation) return;
    waveformRef.current?.playClip(selectedViolation.start_time, selectedViolation.end_time);
  }, [selectedViolation]);

  if (isLoading) {
    return (
      <div className="h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">...</div>
          <div className="text-lg">Loading...</div>
        </div>
      </div>
    );
  }

  if (error && !job) {
    return (
      <div className="h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-lg text-destructive mb-4">{error || "Job not found"}</div>
          <Link href="/">
            <Button>Back to Home</Button>
          </Link>
        </div>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-lg text-destructive mb-4">Job not found</div>
          <Link href="/">
            <Button>Back to Home</Button>
          </Link>
        </div>
      </div>
    );
  }

  // Processing view - show step-by-step progress
  if (isProcessing(job.status)) {
    const currentStepIndex = PROCESSING_STEPS.findIndex((s) => s.key === job.status);

    return (
      <div className="h-screen bg-background flex flex-col">
        <header className="border-b px-6 py-4">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="sm">
                ← Back
              </Button>
            </Link>
            <div>
              <h1 className="text-xl font-semibold">{job.filename}</h1>
            </div>
          </div>
        </header>

        <div className="flex-1 flex items-center justify-center">
          <div className="w-full max-w-md space-y-6">
            <h2 className="text-lg font-semibold text-center mb-8">Processing Audio</h2>

            {PROCESSING_STEPS.map((step, i) => {
              const isDone = i < currentStepIndex;
              const isCurrent = i === currentStepIndex;
              const isPending = i > currentStepIndex;

              return (
                <div key={step.key} className="flex items-center gap-4">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                    isDone
                      ? "bg-green-100 text-green-700"
                      : isCurrent
                        ? "bg-blue-100 text-blue-700"
                        : "bg-muted text-muted-foreground"
                  }`}>
                    {isDone ? "\u2713" : i + 1}
                  </div>
                  <div className="flex-1">
                    <div className={`font-medium ${
                      isCurrent ? "text-foreground" : isPending ? "text-muted-foreground" : ""
                    }`}>
                      {step.label}
                    </div>
                  </div>
                  {isCurrent && (
                    <div className="text-sm text-muted-foreground animate-pulse">
                      In progress...
                    </div>
                  )}
                  {isDone && (
                    <div className="text-sm text-green-600">Done</div>
                  )}
                </div>
              );
            })}

            {job.status === "failed" && (
              <div className="mt-6 p-4 bg-destructive/10 text-destructive rounded-lg">
                {job.error_message || "Processing failed"}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Completed review view
  const acceptedCount = violations.filter((v) => v.status === "accepted").length;
  const rejectedCount = violations.filter((v) => v.status === "rejected").length;
  const pendingCount = violations.filter((v) => v.status === "pending").length;

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Header */}
      <header className="border-b px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/">
              <Button variant="ghost" size="sm">
                ← Back
              </Button>
            </Link>
            <div>
              <h1 className="text-xl font-semibold">{job.filename}</h1>
              <div className="text-sm text-muted-foreground">
                {job.language?.toUpperCase()} •{" "}
                {Math.floor((job.duration_seconds || 0) / 60)}:
                {String(Math.floor((job.duration_seconds || 0) % 60)).padStart(2, "0")}
              </div>
            </div>
          </div>
          <Badge
            variant={job.status === "completed" ? "default" : "secondary"}
          >
            {job.status}
          </Badge>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Violation List Sidebar */}
        <aside className="w-96 border-r bg-muted/10 overflow-hidden shrink-0">
          <ViolationList
            violations={violations}
            selectedViolation={selectedViolation}
            onSelect={handleViolationSelect}
          />
        </aside>

        {/* Main Panel */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* Waveform */}
          <div className="p-6 border-b shrink-0">
            <Waveform
              ref={waveformRef}
              audioUrl={api.getAudioUrl(jobId)}
              violations={violations}
              selectedViolation={selectedViolation}
              onViolationClick={handleViolationSelect}
            />
          </div>

          {/* Selected Violation Details */}
          <div className="flex-1 p-6 overflow-auto">
            {selectedViolation ? (
              <ViolationCard
                violation={selectedViolation}
                onAccept={() => handleStatusUpdate("accepted")}
                onReject={() => handleStatusUpdate("rejected")}
                onPlayClip={playClip}
                isUpdating={isUpdating}
              />
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground">
                Select a violation to review
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Footer */}
      <footer className="border-t px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6 text-sm">
            <span>
              <span className="font-medium text-green-600">{acceptedCount}</span>{" "}
              Accepted
            </span>
            <span>
              <span className="font-medium">{rejectedCount}</span>{" "}
              Rejected
            </span>
            <span>
              <span className="font-medium text-orange-500">{pendingCount}</span>{" "}
              Pending
            </span>
          </div>

          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkUpdate("accepted")}
              disabled={pendingCount === 0 || isUpdating}
            >
              Accept All
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBulkUpdate("rejected")}
              disabled={pendingCount === 0 || isUpdating}
            >
              Reject All
            </Button>

            {exportReady ? (
              <Button onClick={handleDownload}>
                Download Edited Audio
              </Button>
            ) : (
              <Button
                onClick={handleExport}
                disabled={acceptedCount === 0 || isExporting}
              >
                {isExporting ? "Exporting..." : "Export Audio"}
              </Button>
            )}
          </div>
        </div>
      </footer>

      {/* Error toast */}
      {error && (
        <div className="fixed bottom-20 right-6 p-4 bg-destructive/10 text-destructive rounded-lg shadow-lg">
          <div className="flex items-center gap-2">
            <span>{error}</span>
            <Button variant="ghost" size="sm" onClick={() => setError(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
