/**
 * API client for the CleanCut backend.
 */

/**
 * Where the API is, from the browser's point of view.
 *
 * Relative by default, and proxied to the backend by the Next server (see
 * `next.config.ts`). That is what stops a built frontend from being pinned to
 * whichever origin happened to be set when it was built - the published
 * container image would otherwise point wherever CI pointed it.
 *
 * An absolute NEXT_PUBLIC_API_URL still wins, for anyone who wants the browser
 * to talk to the backend directly. That path is cross-origin, so it needs the
 * backend's CORS_ORIGINS to name the frontend.
 *
 * `||` rather than `??` on purpose: `start.sh` sources the root .env with
 * `set -a`, so a variable left blank there arrives as an empty string rather
 * than as absent, and `??` would take it - leaving every request pointed at a
 * base of "".
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

/**
 * A `URL` for an API path, for the one call that has a query string to build.
 *
 * `new URL` needs a base when what it is given is relative, which `API_BASE`
 * now is - without one it raises `TypeError: Invalid URL` rather than
 * resolving against the page. The base is ignored when NEXT_PUBLIC_API_URL
 * supplies an absolute base, so both configurations go through here unchanged.
 */
function apiUrl(path: string): URL {
  const origin = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  return new URL(`${API_BASE}${path}`, origin);
}

export interface Job {
  id: string;
  filename: string;
  original_filename: string | null;
  media_type: "audio" | "video";
  prompt: string | null;
  status: "pending" | "converting" | "transcribing" | "analyzing" | "exporting" | "completed" | "failed";
  auto_fix: boolean;
  auto_scrub: boolean;
  preset: string | null;
  duration_seconds: number | null;
  language: string | null;
  created_at: string;
  error_message: string | null;
  export_status: ExportStatus;
  export_error: string | null;
  /**
   * Staleness, straight from the server. The export in `exports/` is current
   * only while `export_revision === edit_revision`; a null `export_revision`
   * means no export of known provenance, which is not the same as stale.
   */
  edit_revision: number;
  export_revision: number | null;
  violation_count: number;
  pending_count: number;
  accepted_count: number;
  rejected_count: number;
}

export interface JobListItem {
  id: string;
  filename: string;
  original_filename: string | null;
  media_type: string;
  prompt: string | null;
  status: string;
  auto_fix: boolean;
  auto_scrub: boolean;
  preset: string | null;
  duration_seconds: number | null;
  created_at: string;
  violation_count: number;
}

/**
 * What the poll gets back: enough to move a card already on screen, and no
 * more. Deliberately not a `Partial<JobListItem>` - the fields here are the
 * ones that actually change while a job runs, and naming them keeps the merge
 * on the home page honest about what it is allowed to overwrite.
 */
export interface ActiveJob {
  id: string;
  status: string;
  export_status: string;
  violation_count: number;
}

export interface Violation {
  id: string;
  job_id: string;
  text: string;
  start_time: number;
  end_time: number;
  label: string | null;
  rule_violated: string | null;
  severity: "high" | "medium" | "low" | null;
  reasoning: string | null;
  status: "pending" | "accepted" | "rejected";
  action: "cut" | "mute";
  /**
   * Why the server refused to apply this one unreviewed. Both are display
   * only: whether a suggestion may be pre-accepted is decided server-side, and
   * a second copy of that rule here is how the two would drift apart.
   *
   * `is_approximate` - the quote could not be matched to the transcript, so
   * the span is the model's estimate. `is_ambiguous` - the word is only
   * sometimes a filler ("like", "you know").
   */
  is_approximate: boolean;
  is_ambiguous: boolean;
}

/** One line of the stored transcript, with the timing the panel seeks to. */
export interface TranscriptSegment {
  start: number;
  end: number;
  text: string;
}

export interface Transcript {
  job_id: string;
  language: string | null;
  duration: number | null;
  segments: TranscriptSegment[];
}

export interface Preset {
  id: string;
  name: string;
  description: string;
}

/**
 * Export runs on the worker queue, so a job's export has its own lifecycle
 * independent of `status`: a failed render leaves a completed job completed.
 */
export type ExportStatus = "none" | "queued" | "exporting" | "ready" | "failed";

export interface ExportResponse {
  job_id: string;
  export_filename: string;
  message: string;
  export_status: ExportStatus;
}

export interface AdminStats {
  total_jobs: number;
  total_violations: number;
  jobs_by_status: Record<string, number>;
  total_uploads_size_mb: number;
  total_exports_size_mb: number;
  files_count: number;
}

const ADMIN_TOKEN_KEY = "cleancut.adminToken";

/**
 * The admin secret, if the operator has entered one.
 *
 * The destructive routes require it unless the server was started with
 * ALLOW_UNAUTHENTICATED_ADMIN=1. An empty token still sends no header at all: a
 * server with no ADMIN_TOKEN configured answers 503 whatever we send, and its
 * message is the one worth showing.
 */
export function getAdminToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = token.trim();
    if (trimmed) window.localStorage.setItem(ADMIN_TOKEN_KEY, trimmed);
    else window.localStorage.removeItem(ADMIN_TOKEN_KEY);
  } catch {
    // A browser with storage blocked still gets a working read-only dashboard.
  }
}

function adminHeaders(): HeadersInit {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}

class APIError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message);
    this.name = "APIError";
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    if (response.status === 401) {
      throw new APIError(
        401,
        "This server requires an admin token. Enter the configured ADMIN_TOKEN above and try again."
      );
    }
    throw new APIError(response.status, error.detail || "Request failed");
  }
  return response.json();
}

export const api = {
  // Jobs
  async uploadAudio(
    file: File,
    prompt: string | null = null,
    autoFix: boolean = false,
    autoScrub: boolean = false,
    preset: string | null = null
  ): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);
    if (prompt && !preset) {
      formData.append("prompt", prompt);
    }
    formData.append("auto_fix", String(autoFix));
    formData.append("auto_scrub", String(autoScrub));
    if (preset) {
      formData.append("preset", preset);
    }

    const response = await fetch(`${API_BASE}/jobs`, {
      method: "POST",
      body: formData,
    });

    return handleResponse<Job>(response);
  },

  async listPresets(): Promise<Preset[]> {
    const response = await fetch(`${API_BASE}/jobs/presets`);
    return handleResponse<Preset[]>(response);
  },

  /**
   * Ask a new question about a transcript that has already been made.
   *
   * Answers 202 with the job in `analyzing`, so the caller starts polling
   * `status` exactly as it does after an upload - no audio is touched and no
   * Whisper pass runs, which is the entire point of the endpoint.
   */
  async reanalyzeJob(
    jobId: string,
    request: { prompt?: string; preset?: string }
  ): Promise<{ job_id: string; prompt: string | null; preset: string | null; status: string }> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/reanalyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    return handleResponse(response);
  },

  /**
   * One bounded page of jobs, newest first.
   *
   * The server caps `limit` regardless of what is asked for; the default here
   * matches the server's own so the common call sends no query string at all.
   */
  async listJobs(options: { limit?: number; offset?: number } = {}): Promise<JobListItem[]> {
    const url = apiUrl("/jobs");
    if (options.limit !== undefined) url.searchParams.set("limit", String(options.limit));
    if (options.offset !== undefined) url.searchParams.set("offset", String(options.offset));
    const response = await fetch(url.toString());
    return handleResponse<JobListItem[]>(response);
  },

  /**
   * Just the jobs still being worked on, for the poll.
   *
   * Everything but the status is immutable while a job runs, so the timer has
   * no reason to re-fetch the whole history to notice one card moving from
   * `transcribing` to `analyzing`.
   */
  async listActiveJobs(): Promise<ActiveJob[]> {
    const response = await fetch(`${API_BASE}/jobs/active`);
    return handleResponse<ActiveJob[]>(response);
  },

  async getJob(jobId: string): Promise<Job> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}`);
    return handleResponse<Job>(response);
  },

  async deleteJob(jobId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new APIError(response.status, "Failed to delete job");
    }
  },

  // Violations
  async getViolations(jobId: string): Promise<Violation[]> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/violations`);
    return handleResponse<Violation[]>(response);
  },

  async updateViolation(
    jobId: string,
    violationId: string,
    update: { status?: string; action?: string }
  ): Promise<Violation> {
    const response = await fetch(
      `${API_BASE}/jobs/${jobId}/violations/${violationId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      }
    );
    return handleResponse<Violation>(response);
  },

  /**
   * Move several suggestions at once.
   *
   * `fromStatus` defaults server-side to pending, which is what keeps "Clean
   * All" from overwriting a decision the reviewer already made by hand. Undo is
   * the same call in reverse: the ids the sweep changed, moved back off
   * `accepted`.
   */
  async bulkUpdateViolations(
    jobId: string,
    update: { status?: string; action?: string; ids?: string[] },
    labels?: string[],
    fromStatus?: string[]
  ): Promise<{ message: string; updated: number }> {
    const url = apiUrl(`/jobs/${jobId}/violations/bulk-update`);
    if (labels && labels.length > 0) {
      labels.forEach(label => url.searchParams.append("labels", label));
    }
    if (fromStatus && fromStatus.length > 0) {
      fromStatus.forEach(status => url.searchParams.append("from_status", status));
    }

    const response = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    return handleResponse<{ message: string; updated: number }>(response);
  },

  /**
   * The transcript the analysis ran on, or null when there isn't one.
   *
   * A 404 here is the normal case for a job processed before transcripts were
   * persisted, so it is not surfaced as an error - the panel just stays hidden.
   * Any other failure still throws, because that one is worth seeing.
   */
  async getTranscript(jobId: string): Promise<Transcript | null> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/transcript`);
    if (response.status === 404) return null;
    return handleResponse<Transcript>(response);
  },

  // Audio
  getAudioUrl(jobId: string): string {
    return `${API_BASE}/jobs/${jobId}/audio`;
  },

  async getWaveform(jobId: string): Promise<{ peaks: number[] }> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/audio/waveform`);
    return handleResponse<{ peaks: number[] }>(response);
  },

  // Export
  /**
   * Export the edited file. Omit `action` to honor each violation's own
   * cut/mute setting; pass one to force it globally.
   */
  async exportAudio(
    jobId: string,
    action?: "cut" | "mute"
  ): Promise<ExportResponse> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edit_action: action ?? null }),
    });
    return handleResponse<ExportResponse>(response);
  },

  getExportDownloadUrl(jobId: string): string {
    return `${API_BASE}/jobs/${jobId}/export/download`;
  },

  getExportStreamUrl(jobId: string): string {
    return `${API_BASE}/jobs/${jobId}/export/stream`;
  },

  // Admin
  async getAdminStats(): Promise<AdminStats> {
    const response = await fetch(`${API_BASE}/admin/stats`);
    return handleResponse<AdminStats>(response);
  },

  async resetDatabase(): Promise<{ message: string }> {
    const response = await fetch(`${API_BASE}/admin/reset-database`, {
      method: "POST",
      headers: adminHeaders(),
    });
    return handleResponse<{ message: string }>(response);
  },

  async clearStorage(): Promise<{ message: string }> {
    const response = await fetch(`${API_BASE}/admin/clear-storage`, {
      method: "POST",
      headers: adminHeaders(),
    });
    return handleResponse<{ message: string }>(response);
  },

  async resetAll(): Promise<{ message: string; database: string; storage: string }> {
    const response = await fetch(`${API_BASE}/admin/reset-all`, {
      method: "POST",
      headers: adminHeaders(),
    });
    return handleResponse<{ message: string; database: string; storage: string }>(response);
  },
};
