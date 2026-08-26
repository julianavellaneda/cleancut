/**
 * API client for the CleanCut backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

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
 * The backend only requires this when ADMIN_TOKEN is set server-side, so an
 * absent token is the normal local-dev case, not an error. The header is simply
 * omitted then.
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

  async listJobs(): Promise<JobListItem[]> {
    const response = await fetch(`${API_BASE}/jobs`);
    return handleResponse<JobListItem[]>(response);
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

  async bulkUpdateViolations(
    jobId: string,
    update: { status?: string; action?: string },
    labels?: string[]
  ): Promise<{ message: string }> {
    const url = new URL(`${API_BASE}/jobs/${jobId}/violations/bulk-update`);
    if (labels && labels.length > 0) {
      labels.forEach(label => url.searchParams.append("labels", label));
    }

    const response = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    });
    return handleResponse<{ message: string }>(response);
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
