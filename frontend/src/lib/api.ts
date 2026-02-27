/**
 * API client for the Audio Compliance backend.
 */

const API_BASE = "http://localhost:8000/api";

export interface Job {
  id: string;
  filename: string;
  status: "pending" | "processing" | "transcribing" | "analyzing" | "exporting" | "completed" | "failed";
  auto_fix: boolean;
  duration_seconds: number | null;
  language: string | null;
  created_at: string;
  error_message: string | null;
  violation_count: number;
  pending_count: number;
  accepted_count: number;
  rejected_count: number;
}

export interface JobListItem {
  id: string;
  filename: string;
  status: string;
  auto_fix: boolean;
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
  rule_violated: string | null;
  severity: "high" | "medium" | "low" | null;
  reasoning: string | null;
  status: "pending" | "accepted" | "rejected";
  edit_action: "cut" | "mute";
}

export interface ExportResponse {
  job_id: string;
  export_filename: string;
  message: string;
}

export interface AdminStats {
  total_jobs: number;
  total_violations: number;
  jobs_by_status: Record<string, number>;
  total_uploads_size_mb: number;
  total_exports_size_mb: number;
  files_count: number;
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
    throw new APIError(response.status, error.detail || "Request failed");
  }
  return response.json();
}

export const api = {
  // Jobs
  async uploadAudio(file: File, autoFix: boolean = false): Promise<Job> {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${API_BASE}/jobs?auto_fix=${autoFix}`, {
      method: "POST",
      body: formData,
    });

    return handleResponse<Job>(response);
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
    update: { status?: string; edit_action?: string }
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
    update: { status?: string; edit_action?: string }
  ): Promise<{ message: string }> {
    const response = await fetch(
      `${API_BASE}/jobs/${jobId}/violations/bulk-update`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      }
    );
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
  async exportAudio(
    jobId: string,
    editAction: "cut" | "mute" = "cut"
  ): Promise<ExportResponse> {
    const response = await fetch(`${API_BASE}/jobs/${jobId}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edit_action: editAction }),
    });
    return handleResponse<ExportResponse>(response);
  },

  getExportDownloadUrl(jobId: string): string {
    return `${API_BASE}/jobs/${jobId}/export/download`;
  },

  // Admin
  async getAdminStats(): Promise<AdminStats> {
    const response = await fetch(`${API_BASE}/admin/stats`);
    return handleResponse<AdminStats>(response);
  },

  async resetDatabase(): Promise<{ message: string }> {
    const response = await fetch(`${API_BASE}/admin/reset-database`, {
      method: "POST",
    });
    return handleResponse<{ message: string }>(response);
  },

  async clearStorage(): Promise<{ message: string }> {
    const response = await fetch(`${API_BASE}/admin/clear-storage`, {
      method: "POST",
    });
    return handleResponse<{ message: string }>(response);
  },

  async resetAll(): Promise<{ message: string; database: string; storage: string }> {
    const response = await fetch(`${API_BASE}/admin/reset-all`, {
      method: "POST",
    });
    return handleResponse<{ message: string; database: string; storage: string }>(response);
  },
};
