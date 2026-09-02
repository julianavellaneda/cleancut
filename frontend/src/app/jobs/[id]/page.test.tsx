/**
 * The review page: the download button describes the file that actually exists.
 *
 * Regression: staleness lived in a `exportStale` boolean inside this component.
 * It was set on every edit, which covered the common path, but it was also the
 * *only* record of it - so a reload, a second tab, or the poll replacing the
 * job object put "Download edited file" back next to a file rendered from an edit
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
  is_approximate: false,
  is_ambiguous: false,
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
  vi.spyOn(api, "getExportDownloadUrl").mockReturnValue("http://example.test/export");
  // The header turns the job's preset id into a name with this, so the page
  // asks for it on every load.
  vi.spyOn(api, "listPresets").mockResolvedValue([
    { id: "pii-redaction", name: "PII Redaction", description: "" },
  ]);
});

// A real link once the file exists, so the browser can save it - and the query
// changing role is the assertion that it stayed one.
const downloadLink = () => screen.queryByRole("link", { name: "Download edited file" });
const exportButton = () => screen.queryByRole("button", { name: /^Export \d+ edit/ });

describe("an export whose revision matches the edit set", () => {
  it("offers the download", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());

    render(<ReviewPage />);

    await waitFor(() => expect(downloadLink()).toBeInTheDocument());
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
    expect(downloadLink()).not.toBeInTheDocument();
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

    await waitFor(() => expect(downloadLink()).toBeInTheDocument());
  });
});

describe("deciding on an edit after an export finished", () => {
  it("withdraws the download, mirroring the retirement the server just did", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());
    vi.spyOn(api, "updateViolation").mockResolvedValue({ ...violation, status: "rejected" });

    render(<ReviewPage />);
    await waitFor(() => expect(downloadLink()).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Undo Status" }));

    await waitFor(() => expect(downloadLink()).not.toBeInTheDocument());
  });
});

describe("moving the selection", () => {
  /**
   * `loadData` deliberately does not read `selectedViolation` - it seeds the
   * selection through the functional setter instead - so it depends on nothing
   * but the job id and the effect that runs it can list it honestly.
   *
   * This guards the obvious wrong fix for that effect's exhaustive-deps
   * warning: leave `selectedViolation` in `loadData`'s dependencies and add
   * `loadData` to the effect's, and every click in the sidebar re-fetches the
   * job *and* the whole violation list.
   */
  it("re-fetches nothing", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());
    vi.spyOn(api, "getViolations").mockResolvedValue([
      violation,
      { ...violation, id: "v2", label: "Filler Word", text: "um", status: "pending" },
    ]);

    render(<ReviewPage />);
    await waitFor(() => expect(screen.getByText("Filler Word")).toBeInTheDocument());
    expect(api.getJob).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByText("Filler Word"));

    await waitFor(() =>
      expect(screen.getByRole("option", { selected: true })).toHaveTextContent("Filler Word")
    );
    expect(api.getJob).toHaveBeenCalledTimes(1);
    expect(api.getViolations).toHaveBeenCalledTimes(1);
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

describe("a render that failed", () => {
  it("puts the reason and the retry in one banner, and nothing in the header", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(
      job({ export_status: "failed", export_error: "ffmpeg exited 1", export_revision: null })
    );
    const exportAudio = vi.spyOn(api, "exportAudio").mockResolvedValue({
      job_id: "job-1", export_filename: "job-1_edited.mp3",
      message: "queued", export_status: "queued",
    });

    render(<ReviewPage />);

    await waitFor(() => expect(screen.getByText("ffmpeg exited 1")).toBeInTheDocument());
    // The retry lives with the explanation rather than being a second export
    // button in the header saying nothing about why the first one failed.
    expect(exportButton()).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry export" }));

    expect(exportAudio).toHaveBeenCalledWith("job-1");
  });
});

describe("a completed job carrying a warning", () => {
  it("renders it without claiming the job failed", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(
      job({ error_message: "Partial analysis: 1 of 4 chunks failed" })
    );

    render(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByText("Partial analysis: 1 of 4 chunks failed")).toBeInTheDocument()
    );
    expect(screen.getByText("Heads up")).toBeInTheDocument();
    // Still the review screen, not the failure screen.
    expect(downloadLink()).toBeInTheDocument();
  });
});

describe("the transcript column", () => {
  /**
   * The grid is the layout mechanism, so opening the transcript has to be a
   * change to the grid rather than a fourth `<aside>` squeezing the middle.
   * `data-transcript` is what the stylesheet keys the second column set off, so
   * that attribute is the honest thing to assert on.
   */
  it("re-shapes the grid rather than being appended to it", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(job());
    vi.spyOn(api, "getTranscript").mockResolvedValue({
      job_id: "job-1",
      language: "en",
      duration: 60,
      segments: [{ start: 0, end: 2, text: "hello there" }],
    });

    const { container } = render(<ReviewPage />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Transcript" })).toBeInTheDocument()
    );

    const grid = container.querySelector(".review-grid");
    expect(grid).toHaveAttribute("data-transcript", "closed");

    await userEvent.click(screen.getByRole("button", { name: "Transcript" }));

    expect(grid).toHaveAttribute("data-transcript", "open");
    expect(screen.getByText("hello there")).toBeInTheDocument();
  });
});
