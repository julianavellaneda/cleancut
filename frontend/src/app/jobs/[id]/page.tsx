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

  // Load job and violations
  useEffect(() => {
    async function loadData() {
      setIsLoading(true);
      try {
        const [jobData, violationsData] = await Promise.all([
          api.getJob(jobId),
          api.getViolations(jobId),
        ]);
        setJob(jobData);
        setViolations(violationsData);

        // Select first violation by default
        if (violationsData.length > 0) {
          setSelectedViolation(violationsData[0]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load job");
      } finally {
        setIsLoading(false);
      }
    }

    loadData();
  }, [jobId]);

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

        // Update local state
        setViolations((prev) =>
          prev.map((v) => (v.id === updated.id ? updated : v))
        );
        setSelectedViolation(updated);

        // Update job counts
        const jobData = await api.getJob(jobId);
        setJob(jobData);

        // Reset export ready state
        setExportReady(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update");
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
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">⏳</div>
          <div className="text-lg">Loading...</div>
        </div>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center">
          <div className="text-4xl mb-4">❌</div>
          <div className="text-lg text-destructive mb-4">{error || "Job not found"}</div>
          <Link href="/">
            <Button>Back to Home</Button>
          </Link>
        </div>
      </div>
    );
  }

  const acceptedCount = violations.filter((v) => v.status === "accepted").length;
  const rejectedCount = violations.filter((v) => v.status === "rejected").length;
  const pendingCount = violations.filter((v) => v.status === "pending").length;

  return (
    <div className="min-h-screen bg-background flex flex-col">
      {/* Header */}
      <header className="border-b px-6 py-4">
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
      <div className="flex-1 flex">
        {/* Violation List Sidebar */}
        <aside className="w-80 border-r bg-muted/10">
          <ViolationList
            violations={violations}
            selectedViolation={selectedViolation}
            onSelect={handleViolationSelect}
          />
        </aside>

        {/* Main Panel */}
        <main className="flex-1 flex flex-col">
          {/* Waveform */}
          <div className="p-6 border-b">
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
      <footer className="border-t px-6 py-4">
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
            {exportReady ? (
              <Button onClick={handleDownload}>
                📥 Download Edited Audio
              </Button>
            ) : (
              <Button
                onClick={handleExport}
                disabled={acceptedCount === 0 || isExporting}
              >
                {isExporting ? "Exporting..." : "📤 Export Audio"}
              </Button>
            )}
          </div>
        </div>
      </footer>
    </div>
  );
}
