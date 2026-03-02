"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api, JobListItem } from "@/lib/api";

export default function UploadPage() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [autoFix, setAutoFix] = useState(false);
  const [autoScrub, setAutoScrub] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ [key: string]: string }>({});
  
  const pollInterval = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    loadJobs();
    // Start polling for updates if there are active jobs
    startPolling();
    return () => stopPolling();
  }, []);

  async function loadJobs() {
    setLoadingJobs(true);
    try {
      const jobList = await api.listJobs();
      setJobs(jobList);
      
      // If any jobs are not completed/failed, ensure polling is active
      const hasActiveJobs = jobList.some(j => !["completed", "failed"].includes(j.status));
      if (hasActiveJobs) {
        startPolling();
      }
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
        if (!hasActiveJobs) {
          stopPolling();
        }
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
    if (files.length > 0) {
      handleFiles(files);
    }
  }, []);

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files ? Array.from(e.target.files) : [];
      if (files.length > 0) {
        handleFiles(files);
      }
    },
    []
  );

  async function handleFiles(files: File[]) {
    const allowedExtensions = /\.(mp3|wav|m4a|flac|ogg|webm|aif|aiff|mp4|mov)$/i;
    const validFiles = files.filter(file => allowedExtensions.test(file.name));

    if (validFiles.length === 0) {
      setError("Please upload valid audio/video files (MP3, WAV, M4A, FLAC, OGG, WEBM, AIFF, MP4, or MOV)");
      return;
    }

    setError(null);
    setIsUploading(true);

    // Upload files one by one (they are queued on backend anyway)
    for (const file of validFiles) {
      setUploadProgress(prev => ({ ...prev, [file.name]: "Uploading..." }));
      try {
        await api.uploadAudio(file, prompt, autoFix, autoScrub);
        setUploadProgress(prev => ({ ...prev, [file.name]: "Queued" }));
      } catch (err) {
        setUploadProgress(prev => ({ ...prev, [file.name]: "Failed" }));
        setError(err instanceof Error ? err.message : "Upload failed");
      }
    }

    setIsUploading(false);
    loadJobs();
    startPolling();
    
    // Clear upload progress after a delay
    setTimeout(() => {
      setUploadProgress({});
    }, 5000);
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

  function getStatusIcon(status: string) {
    switch (status) {
      case "completed": return "✅";
      case "failed": return "❌";
      case "pending": return "⏳";
      case "converting":
      case "transcribing":
      case "analyzing":
      case "exporting": return "🔄";
      default: return "⏳";
    }
  }

  function getStatusProgress(status: string) {
    switch (status) {
      case "pending": return 10;
      case "converting": return 25;
      case "transcribing": return 50;
      case "analyzing": return 75;
      case "exporting": return 90;
      case "completed": return 100;
      default: return 0;
    }
  }

  const activeJobs = jobs.filter(j => !["completed", "failed"].includes(j.status));
  const completedJobs = jobs.filter(j => j.status === "completed");

  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">AI Media Editor</h1>
        <p className="text-muted-foreground mb-8">
          Upload audio or video and describe the edits you want to make
        </p>

        {/* Upload Area */}
        <Card className="mb-8">
          <CardContent className="pt-6">
            <div className="space-y-4 mb-6">
              <div className="space-y-2">
                <label htmlFor="prompt" className="text-sm font-medium">
                  What would you like to do?
                </label>
                <textarea
                  id="prompt"
                  placeholder="e.g., Remove all filler words, mute parts where I talk about the price, or find segments where the speaker is talking about income claims."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  className="w-full min-h-[100px] p-3 rounded-md border border-input bg-background text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
              
              <div className="flex flex-col gap-2 p-4 bg-muted/50 rounded-lg">
                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="auto-fix"
                    checked={autoFix}
                    onChange={(e) => setAutoFix(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <label
                    htmlFor="auto-fix"
                    className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                  >
                    Auto-apply all AI suggested edits (Markers based on your prompt)
                  </label>
                </div>
                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="auto-scrub"
                    checked={autoScrub}
                    onChange={(e) => setAutoScrub(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-primary focus:ring-primary"
                  />
                  <label
                    htmlFor="auto-scrub"
                    className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
                  >
                    Auto-apply "Scrubber" edits (Remove silences and filler words)
                  </label>
                </div>
              </div>
            </div>

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
                multiple
                accept="audio/*,video/*,.mp3,.wav,.m4a,.flac,.ogg,.webm,.aif,.aiff,.mp4,.mov"
                onChange={handleFileInput}
                className="hidden"
                disabled={isUploading}
              />

              {isUploading ? (
                <div className="space-y-4">
                  <div className="text-lg font-medium">Uploading Files...</div>
                  <div className="max-w-xs mx-auto space-y-2">
                    {Object.entries(uploadProgress).map(([name, status]) => (
                      <div key={name} className="flex justify-between text-xs">
                        <span className="truncate mr-4">{name}</span>
                        <span className="font-semibold">{status}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="text-6xl">🎥</div>
                  <div className="text-lg font-medium">
                    Drag and drop media files here
                  </div>
                  <p className="text-muted-foreground">
                    or click to browse
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Supports MP3, WAV, M4A, FLAC, MP4, MOV, and more
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

        {/* Processing Summary */}
        {(activeJobs.length > 0) && (
          <div className="mb-4 flex items-center justify-between bg-primary/10 p-4 rounded-lg border border-primary/20">
            <div className="flex items-center gap-4">
              <div className="flex flex-col">
                <span className="text-sm font-medium">Processing Queue</span>
                <span className="text-2xl font-bold">{activeJobs.length} Files Left</span>
              </div>
              <div className="h-8 w-px bg-primary/20" />
              <div className="flex flex-col">
                <span className="text-sm text-muted-foreground">Current Step</span>
                <span className="text-sm font-semibold capitalize">{activeJobs[activeJobs.length - 1].status}...</span>
              </div>
            </div>
            <div className="text-right">
              <span className="text-sm text-muted-foreground">{completedJobs.length} completed</span>
            </div>
          </div>
        )}

        {/* Job List */}
        {jobs.length > 0 && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
              <CardTitle>Files</CardTitle>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => loadJobs()}
                disabled={loadingJobs}
              >
                {loadingJobs ? "Refreshing..." : "Refresh"}
              </Button>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {jobs.map((job) => (
                  <div
                    key={job.id}
                    className={`flex flex-col p-4 rounded-lg border transition-colors ${
                      job.status === 'completed' ? 'bg-card' : 'bg-muted/30'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="text-xl flex-shrink-0">
                          {getStatusIcon(job.status)}
                        </span>
                        <div className="min-w-0">
                          <div className="font-medium truncate">{job.original_filename || job.filename}</div>
                          <div className="text-xs text-muted-foreground">
                            {formatDate(job.created_at)} • {formatDuration(job.duration_seconds)}
                            {job.prompt && ` • "${job.prompt.substring(0, 30)}${job.prompt.length > 30 ? '...' : ''}"`}
                          </div>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-2">
                        {job.status === "completed" ? (
                          job.auto_fix ? (
                            <Button 
                              size="sm" 
                              variant="outline"
                              className="h-8"
                              onClick={() => window.open(api.getExportDownloadUrl(job.id))}
                            >
                              Download
                            </Button>
                          ) : (
                            <Button 
                              size="sm" 
                              className="h-8"
                              onClick={() => router.push(`/jobs/${job.id}`)}
                            >
                              Review
                            </Button>
                          )
                        ) : job.status === "failed" ? (
                          <span className="text-xs text-destructive font-medium">Failed</span>
                        ) : (
                          <span className="text-xs font-medium capitalize">{job.status}...</span>
                        )}
                      </div>
                    </div>
                    
                    {!["completed", "failed"].includes(job.status) && (
                      <div className="mt-2">
                        <Progress value={getStatusProgress(job.status)} className="h-1" />
                      </div>
                    )}

                    {job.status === "completed" && job.violation_count > 0 && (
                      <div className="mt-1 text-xs text-muted-foreground">
                        {job.violation_count} suggested edit{job.violation_count !== 1 ? "s" : ""}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
