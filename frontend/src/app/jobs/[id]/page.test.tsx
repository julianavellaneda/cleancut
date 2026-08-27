/**
 * The review page: the download button describes the file that actually exists.
 *
 * Regression: staleness lived in a `exportStale` boolean inside this component.
 * It was set on every edit, which covered the common path, but it was also the
 * *only* record of it - so a reload, a second tab, or the poll replacing the
 * job object put "Download Master" back next to a file rendered from an edit
 * list the reviewer had since changed. The server now tracks it as a pair of
 * revisions and the page reads them.
 *
 * The Waveform is mocked out: it constructs a real WaveSurfer against an audio
 * element jsdom cannot decode, and none of it is what these assert on.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "./page";
import { api, Job, Violation } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "job-1" }),
}));

vi.mock("@/components/Waveform", () => ({
  Waveform: () => <div data-testid="waveform" />,
}));

const violation: Violation = {
  id: "v1",
  job_id: "job-1",
  text: "I made eleven thousand dollars",
  start_time: 1,
  end_time: 2,
  label: "Income Claim",
  rule_violated: null,
  severity: "high",
  reasoning: "an earnings claim",
  status: "accepted",
  action: "cut",
};

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    filename: "job-1.mp3",
    original_filename: "seminar.mp3",
    media_type: "audio",
    prompt: "find income claims",
    status: "completed",
    auto_fix: false,
    auto_scrub: false,
    preset: null,
    duration_seconds: 60,
    language: "en",
    created_at: "2026-01-01T00:00:00",
    error_message: null,
    export_status: "ready",
    export_error: null,
    edit_revision: 0,
    export_revision: 0,
    violation_count: 1,
    pending_count: 0,
    accepted_count: 1,
    rejected_count: 0,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(api, "getViolations").mockResolvedValue([violation]);
  vi.spyOn(api, "getTranscript").mockResolvedValue(null);
  vi.spyOn(api, "getAudioUrl").mockReturnValue("http://example.test/audio");
});

const downloadButton = () => screen.queryByRole("button", { name: "Download Master" });
const exportButton = () => screen.queryByRole("button", { name: "Export Edited" });

describe("an export whose revision matches the edit set", () => {
  it("offers the download", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());

    render(<ReviewPage />);

    await waitFor(() => expect(downloadButton()).toBeInTheDocument());
  });
});

describe("an export the server has already superseded", () => {
  it("is not offered for download, whatever export_status says", async () => {
    // The state a second tab, or a reload after an edit, lands in: the render
    // finished, but it came from an earlier revision of the edit list.
    vi.spyOn(api, "getJob").mockResolvedValue(
      job({ export_status: "ready", export_revision: 2, edit_revision: 5 })
    );

    render(<ReviewPage />);

    await waitFor(() => expect(exportButton()).toBeInTheDocument());
    expect(downloadButton()).not.toBeInTheDocument();
  });
});

describe("an export of unknown provenance", () => {
  it("is still offered, because unknown is not stale", async () => {
    // A row from before the revision columns: a file the filesystem probe finds
    // and nothing recording which edits made it. That download works today.
    vi.spyOn(api, "getJob").mockResolvedValue(
      job({ export_status: "ready", export_revision: null, edit_revision: 3 })
    );

    render(<ReviewPage />);

    await waitFor(() => expect(downloadButton()).toBeInTheDocument());
  });
});

describe("deciding on an edit after an export finished", () => {
  it("withdraws the download, mirroring the retirement the server just did", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());
    vi.spyOn(api, "updateViolation").mockResolvedValue({ ...violation, status: "rejected" });

    render(<ReviewPage />);
    await waitFor(() => expect(downloadButton()).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Undo Status" }));

    await waitFor(() => expect(downloadButton()).not.toBeInTheDocument());
  });
});

describe("an edit made while a render is in flight", () => {
  it("leaves the in-flight state alone for the worker to settle", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(
      job({ export_status: "exporting", export_revision: null })
    );
    vi.spyOn(api, "updateViolation").mockResolvedValue({ ...violation, status: "rejected" });

    render(<ReviewPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Exporting…" })).toBeInTheDocument()
    );

    await userEvent.click(screen.getByRole("button", { name: "Undo Status" }));

    await waitFor(() => expect(api.updateViolation).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Exporting…" })).toBeInTheDocument();
  });
});
