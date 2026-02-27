"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, JobListItem } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);

  useEffect(() => {
    loadJobs();
  }, []);

  async function loadJobs() {
    setLoadingJobs(true);
    try {
      const jobList = await api.listJobs();
      setJobs(jobList);
    } catch {
      // Ignore errors loading jobs
    } finally {
      setLoadingJobs(false);
    }
  }

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFile(files[0]);
    }
  }, []);

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleFile(files[0]);
      }
    },
    []
  );

  async function handleFile(file: File) {
    const allowedTypes = [
      "audio/mpeg",
      "audio/wav",
      "audio/mp4",
      "audio/x-m4a",
      "audio/flac",
      "audio/ogg",
      "audio/webm",
      "audio/x-aiff",
      "audio/aiff",
    ];

    if (!allowedTypes.includes(file.type) && !file.name.match(/\.(mp3|wav|m4a|flac|ogg|webm|aif|aiff)$/i)) {
      setError("Please upload an audio file (MP3, WAV, M4A, FLAC, OGG, WEBM, or AIFF)");
      return;
    }

    setError(null);
    setIsUploading(true);

    try {
      const job = await api.uploadAudio(file);
      // Redirect to job page immediately - processing runs in background
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setIsUploading(false);
    }
  }

  function formatDuration(seconds: number | null): string {
    if (seconds === null) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">Audio Compliance Review</h1>
        <p className="text-muted-foreground mb-8">
          Upload audio to analyze for compliance violations
        </p>

        {/* Upload Area */}
        <Card className="mb-8">
          <CardContent className="pt-6">
            <div
              className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25 hover:border-muted-foreground/50"
              } ${isUploading ? "pointer-events-none opacity-50" : "cursor-pointer"}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() =>
                !isUploading &&
                document.getElementById("file-input")?.click()
              }
            >
              <input
                id="file-input"
                type="file"
                accept="audio/*,.mp3,.wav,.m4a,.flac,.ogg,.webm,.aif,.aiff"
                onChange={handleFileInput}
                className="hidden"
                disabled={isUploading}
              />

              {isUploading ? (
                <div className="space-y-4">
                  <div className="text-lg font-medium">Uploading...</div>
                  <p className="text-sm text-muted-foreground">
                    Saving file, please wait
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="text-6xl">🎵</div>
                  <div className="text-lg font-medium">
                    Drag and drop audio file here
                  </div>
                  <p className="text-muted-foreground">
                    or click to browse
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Supports MP3, WAV, M4A, FLAC, OGG, WEBM, AIFF
                  </p>
                </div>
              )}
            </div>

            {error && (
              <div className="mt-4 p-4 bg-destructive/10 text-destructive rounded-lg">
                {error}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Recent Jobs */}
        {jobs.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Recent Jobs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {jobs.map((job) => (
                  <div
                    key={job.id}
                    className="flex items-center justify-between p-3 rounded-lg hover:bg-muted/50 cursor-pointer transition-colors"
                    onClick={() => router.push(`/jobs/${job.id}`)}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-2xl">
                        {job.status === "completed" ? "✅" : job.status === "failed" ? "❌" : job.status === "transcribing" || job.status === "analyzing" ? "🔄" : "⏳"}
                      </span>
                      <div>
                        <div className="font-medium">{job.filename}</div>
                        <div className="text-sm text-muted-foreground">
                          {formatDate(job.created_at)} • {formatDuration(job.duration_seconds)}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-medium">
                        {job.violation_count} violation{job.violation_count !== 1 ? "s" : ""}
                      </div>
                      <div className="text-sm text-muted-foreground capitalize">
                        {job.status}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <Button
                variant="outline"
                className="w-full mt-4"
                onClick={() => loadJobs()}
                disabled={loadingJobs}
              >
                {loadingJobs ? "Loading..." : "Refresh"}
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
