"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, JobListItem } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function UploadPage() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [autoFix, setAutoFix] = useState(false);
  const [autoScrub, setAutoScrub] = useState(false);
  const [bsmMode, setBsmMode] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ [key: string]: string }>({});
  
  const pollInterval = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    loadJobs();
    startPolling();
    return () => stopPolling();
  }, []);

  async function loadJobs() {
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
  }

  function startPolling() {
    if (pollInterval.current) return;
    pollInterval.current = setInterval(async () => {
      try {
        const jobList = await api.listJobs();
        setJobs(jobList);
        const hasActiveJobs = jobList.some(j => !["completed", "failed"].includes(j.status));
        if (!hasActiveJobs) stopPolling();
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 3000);
  }

  function stopPolling() {
    if (pollInterval.current) {
      clearInterval(pollInterval.current);
      pollInterval.current = null;
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
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) handleFiles(files);
  }, []);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length > 0) handleFiles(files);
  }, []);

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
        await api.uploadAudio(file, prompt, autoFix, autoScrub, bsmMode);
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

  const activeJobs = jobs.filter(j => !["completed", "failed"].includes(j.status));

  return (
    <div className="container max-w-4xl mx-auto py-12 px-6 space-y-12">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight">AI Media Editor</h1>
        <p className="text-muted-foreground">Minimalist media editing powered by AI.</p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Create New Edit</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="prompt" className="text-sm font-medium">
                Instructions {bsmMode && <span className="text-xs font-normal text-muted-foreground">(disabled — strict preset active)</span>}
              </label>
              <textarea
                id="prompt"
                placeholder={bsmMode ? "Strict rulebook compliance analysis is active." : "E.g., Remove filler words and silences..."}
                value={bsmMode ? "" : prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={bsmMode}
                className={cn(
                  "w-full min-h-[100px] p-3 rounded-md border border-input bg-background text-sm focus:ring-1 focus:ring-primary outline-none transition-all",
                  bsmMode && "opacity-50 cursor-not-allowed"
                )}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <label className="flex items-center gap-3 p-3 border rounded-md cursor-pointer hover:bg-muted/50 transition-colors">
                <input
                  type="checkbox"
                  checked={autoFix}
                  onChange={(e) => setAutoFix(e.target.checked)}
                  className="w-4 h-4 rounded border-input"
                />
                <span className="text-sm font-medium">Auto-apply markers</span>
              </label>
              <label className="flex items-center gap-3 p-3 border rounded-md cursor-pointer hover:bg-muted/50 transition-colors">
                <input
                  type="checkbox"
                  checked={autoScrub}
                  onChange={(e) => setAutoScrub(e.target.checked)}
                  className="w-4 h-4 rounded border-input"
                />
                <span className="text-sm font-medium">Scrubber mode</span>
              </label>
              <label className={cn(
                "flex items-center gap-3 p-3 border rounded-md cursor-pointer transition-colors",
                bsmMode ? "border-primary bg-primary/5" : "hover:bg-muted/50"
              )}>
                <input
                  type="checkbox"
                  checked={bsmMode}
                  onChange={(e) => setBsmMode(e.target.checked)}
                  className="w-4 h-4 rounded border-input"
                />
                <span className="text-sm font-medium">Strict Compliance Mode</span>
              </label>
            </div>
            {bsmMode && (
              <div className="text-xs text-muted-foreground px-1">
                Strict marketing-guidelines analysis. The custom prompt is ignored while this is on.
              </div>
            )}
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
