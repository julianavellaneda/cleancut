/**
 * The upload page: what the form says is what gets uploaded.
 *
 * Regression: `handleDrop` and `handleFileInput` were `useCallback(..., [])`.
 * They call `handleFiles`, which closes over prompt, preset, autoFix and
 * autoScrub - so both handlers were frozen around the first render and every
 * upload sent the initial values. The prompt box, the preset select and both
 * checkboxes were silently inert; a user asking for one thing got a default
 * analysis of another.
 *
 * These assert on the arguments `api.uploadAudio` is called with, because that
 * is the only place the settings and the file meet. A render assertion would
 * have passed throughout the bug: the controls always *displayed* correctly.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UploadPage from "./page";
import { api, JobListItem } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

function uploadArgs() {
  const call = vi.mocked(api.uploadAudio).mock.calls.at(-1);
  if (!call) throw new Error("api.uploadAudio was never called");
  const [file, prompt, autoFix, autoScrub, preset] = call;
  return { file, prompt, autoFix, autoScrub, preset };
}

const media = () => new File(["audio"], "seminar.mp3", { type: "audio/mpeg" });

beforeEach(() => {
  // Re-spying an already-spied method keeps the old call log, and every
  // assertion here is a call count or a last call.
  vi.clearAllMocks();
  vi.spyOn(api, "listJobs").mockResolvedValue([]);
  vi.spyOn(api, "listActiveJobs").mockResolvedValue([]);
  vi.spyOn(api, "listPresets").mockResolvedValue([
    { id: "income-claims", name: "Income Claims", description: "Earnings talk." },
  ]);
  vi.spyOn(api, "uploadAudio").mockResolvedValue({} as never);
});

async function fillInSettings() {
  await userEvent.type(screen.getByLabelText(/Instructions/), "cut every guarantee");
  await userEvent.click(screen.getByLabelText("Auto-apply markers"));
  await userEvent.click(screen.getByLabelText("Scrubber mode"));
}

describe("choosing a file through the browse input", () => {
  it("uploads with the prompt and toggles as they stand", async () => {
    render(<UploadPage />);
    await fillInSettings();

    await userEvent.upload(document.getElementById("file-input") as HTMLInputElement, media());

    await waitFor(() => expect(api.uploadAudio).toHaveBeenCalled());
    expect(uploadArgs()).toMatchObject({
      prompt: "cut every guarantee",
      autoFix: true,
      autoScrub: true,
      preset: null,
    });
  });

  it("uploads the preset chosen after the page first rendered", async () => {
    render(<UploadPage />);
    await waitFor(() => expect(screen.getByRole("option", { name: "Income Claims" })).toBeInTheDocument());

    await userEvent.selectOptions(screen.getByLabelText("Rule preset"), "income-claims");
    await userEvent.upload(document.getElementById("file-input") as HTMLInputElement, media());

    await waitFor(() => expect(api.uploadAudio).toHaveBeenCalled());
    expect(uploadArgs().preset).toBe("income-claims");
  });
});

describe("dropping a file on the drop zone", () => {
  /**
   * The drop path had the same frozen closure and is reached by different code,
   * so it is asserted separately rather than assumed to follow the input.
   */
  function drop(file: File) {
    // The drop zone is the element wrapping the hidden file input, which is a
    // steadier handle on it than any of its styling.
    const zone = document.getElementById("file-input")!.parentElement!;
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
  }

  it("uploads with the prompt and toggles as they stand", async () => {
    render(<UploadPage />);
    await fillInSettings();

    drop(media());

    await waitFor(() => expect(api.uploadAudio).toHaveBeenCalled());
    expect(uploadArgs()).toMatchObject({
      prompt: "cut every guarantee",
      autoFix: true,
      autoScrub: true,
    });
  });
});

describe("a multi-file drop", () => {
  /**
   * One request per file, so a blanket "Processing Upload..." cannot say which
   * of them landed and `error` only ever holds the last failure. The per-file
   * state was tracked from the beginning and never rendered, which made a
   * partially failed drop read as a wholly failed one.
   */
  it("names what happened to each file", async () => {
    vi.mocked(api.uploadAudio)
      .mockResolvedValueOnce({} as never)
      .mockRejectedValueOnce(new Error("File exceeds the 500 MB limit"));

    render(<UploadPage />);
    await userEvent.upload(document.getElementById("file-input") as HTMLInputElement, [
      new File(["a"], "keynote.mp3", { type: "audio/mpeg" }),
      new File(["b"], "too-big.wav", { type: "audio/wav" }),
    ]);

    const row = async (name: string) =>
      (await screen.findByText(name)).parentElement as HTMLElement;
    expect(await row("keynote.mp3")).toHaveTextContent("Queued");
    expect(await row("too-big.wav")).toHaveTextContent("Failed");
  });
});

it("loads the job list once, not once per render", async () => {
  // The mount effect now names the four callbacks it calls. That is only safe
  // because each is memoized over nothing reactive; if one stopped being
  // stable, the effect would re-run on every render it caused - so the call
  // count is the assertion that keeps the dependency list honest.
  render(<UploadPage />);

  await waitFor(() => expect(api.listJobs).toHaveBeenCalled());
  await new Promise(resolve => setTimeout(resolve, 100));
  expect(api.listJobs).toHaveBeenCalledTimes(1);
  expect(api.listPresets).toHaveBeenCalledTimes(1);
});

it("still rejects a file the backend would not accept", async () => {
  render(<UploadPage />);

  await userEvent.upload(
    document.getElementById("file-input") as HTMLInputElement,
    new File(["x"], "notes.txt", { type: "text/plain" }),
  );

  expect(await screen.findByText("Invalid file format.")).toBeInTheDocument();
  expect(api.uploadAudio).not.toHaveBeenCalled();
});

// --- polling ---------------------------------------------------------------
//
// The timer used to call `listJobs`, re-fetching every job in the entire
// history every three seconds to notice one card changing stage. With retention
// off by default that request only grows. These pin the smaller shape: ask what
// is active, merge it into what is already rendered, and stop when nothing is.

function jobRow(overrides: Partial<JobListItem> = {}): JobListItem {
  return {
    id: "job-1",
    filename: "job-1.mp3",
    original_filename: "seminar.mp3",
    media_type: "audio",
    prompt: "flag income claims",
    status: "transcribing",
    auto_fix: false,
    auto_scrub: false,
    preset: null,
    duration_seconds: 120,
    created_at: new Date().toISOString(),
    violation_count: 0,
    ...overrides,
  };
}

it("polls the active endpoint rather than the whole job list", async () => {
  vi.useFakeTimers();
  vi.mocked(api.listJobs).mockResolvedValue([jobRow()]);
  vi.mocked(api.listActiveJobs).mockResolvedValue([
    { id: "job-1", status: "analyzing", export_status: "none", violation_count: 3 },
  ]);

  render(<UploadPage />);
  await vi.waitFor(() => expect(api.listJobs).toHaveBeenCalled());
  const initialFullReads = vi.mocked(api.listJobs).mock.calls.length;

  await vi.advanceTimersByTimeAsync(3000);

  expect(api.listActiveJobs).toHaveBeenCalled();
  // The expensive call did not repeat: the tick is answered by the small one.
  expect(vi.mocked(api.listJobs).mock.calls.length).toBe(initialFullReads);

  vi.useRealTimers();
});

it("merges the poll's statuses into the cards already on screen", async () => {
  vi.useFakeTimers();
  vi.mocked(api.listJobs).mockResolvedValue([jobRow()]);
  vi.mocked(api.listActiveJobs).mockResolvedValue([
    { id: "job-1", status: "analyzing", export_status: "none", violation_count: 7 },
  ]);

  render(<UploadPage />);
  // The status is rendered twice per row (the meta line and the pulsing
  // badge), so these count matches rather than expecting exactly one.
  await vi.waitFor(() => expect(screen.getAllByText(/transcribing/i).length).toBeGreaterThan(0));

  await vi.advanceTimersByTimeAsync(3000);

  // The status the poll carried replaced the one the full read set.
  await vi.waitFor(() => {
    expect(screen.getAllByText(/analyzing/i).length).toBeGreaterThan(0);
  });
  expect(screen.queryAllByText(/transcribing/i)).toHaveLength(0);

  // And the row keeps the fields the poll does not carry: the filename came
  // from the full read, and the small response has no opinion about it.
  expect(screen.getByText("seminar.mp3")).toBeInTheDocument();

  vi.useRealTimers();
});

it("stops polling and takes one final full read when nothing is active", async () => {
  vi.useFakeTimers();
  vi.mocked(api.listJobs).mockResolvedValue([jobRow({ status: "completed" })]);
  vi.mocked(api.listActiveJobs).mockResolvedValue([]);

  render(<UploadPage />);
  await vi.waitFor(() => expect(api.listJobs).toHaveBeenCalled());

  await vi.advanceTimersByTimeAsync(3000);
  const afterStop = vi.mocked(api.listActiveJobs).mock.calls.length;

  // The final read is what stops a job that finished between two ticks sitting
  // on screen mid-stage until the page is reloaded.
  expect(vi.mocked(api.listJobs).mock.calls.length).toBeGreaterThan(1);

  // And the timer really is off: further time passes with no further polls.
  await vi.advanceTimersByTimeAsync(9000);
  expect(vi.mocked(api.listActiveJobs).mock.calls.length).toBe(afterStop);

  vi.useRealTimers();
});
