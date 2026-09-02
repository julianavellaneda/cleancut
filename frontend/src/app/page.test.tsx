/**
 * The upload page: what the form says is what gets uploaded.
 *
 * Regression: `handleDrop` and `handleFileInput` were `useCallback(..., [])`.
 * They call `handleFiles`, which closes over prompt, preset, autoFix and
 * autoScrub - so both handlers were frozen around the first render and every
 * upload sent the initial values. The prompt box, the preset picker and both
 * toggles were silently inert; a user asking for one thing got a default
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
    await waitFor(() => expect(screen.getByRole("radio", { name: "Income Claims" })).toBeInTheDocument());

    await userEvent.click(screen.getByRole("radio", { name: "Income Claims" }));
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

// --- the rebuilt controls --------------------------------------------------
//
// The preset `<select>` is now a radiogroup of pills and the two checkboxes are
// switches. Both were queried through their accessible names by the tests
// above, so these pin the roles that keep those names attached: a styled
// `<div>` would render identically and take the whole upload form's coverage
// down with it silently.

describe("the rule preset radiogroup", () => {
  it("is a named group of radios, with prompt mode among them", async () => {
    render(<UploadPage />);

    const group = await screen.findByLabelText("Rule preset");
    expect(group).toHaveAttribute("role", "radiogroup");

    // Prompt mode is an option, not the absence of one. The mockup omits it
    // because its demo always has a preset; without it, picking a preset would
    // be a one-way door.
    const none = screen.getByRole("radio", { name: "None — use my instructions" });
    expect(none).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Income Claims" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("moves and selects with the arrow keys, on one tab stop", async () => {
    render(<UploadPage />);
    const none = await screen.findByRole("radio", { name: "None — use my instructions" });

    // Only the checked option is tabbable: that is what makes Tab step past
    // the group rather than through every option in it.
    expect(none).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "Income Claims" })).toHaveAttribute(
      "tabindex",
      "-1",
    );

    none.focus();
    await userEvent.keyboard("{ArrowDown}");

    const preset = screen.getByRole("radio", { name: "Income Claims" });
    expect(preset).toHaveAttribute("aria-checked", "true");
    expect(preset).toHaveFocus();

    // And it wraps, which is the radiogroup contract rather than a listbox's.
    await userEvent.keyboard("{ArrowDown}");
    expect(none).toHaveAttribute("aria-checked", "true");
  });

  it("says why the instructions box is unavailable, rather than only dimming it", async () => {
    render(<UploadPage />);
    await userEvent.click(await screen.findByRole("radio", { name: "Income Claims" }));

    expect(screen.getByLabelText(/Instructions/)).toBeDisabled();
    // The reason is readable, which is the point of the overlay: a 50% dim says
    // the control is unavailable and never says how to get it back.
    expect(
      screen.getByText(/rulebook is driving this analysis/i),
    ).toBeInTheDocument();
  });
});

describe("the two toggles", () => {
  it("are switches that report their own state", async () => {
    render(<UploadPage />);

    const autoFix = screen.getByLabelText("Auto-apply markers");
    expect(autoFix).toHaveAttribute("role", "switch");
    expect(autoFix).toHaveAttribute("aria-checked", "false");

    await userEvent.click(autoFix);
    expect(autoFix).toHaveAttribute("aria-checked", "true");

    // The accessible name is the title alone. The description sits in
    // `aria-describedby`, so it does not swallow the name the queries use.
    expect(autoFix).toHaveAccessibleDescription(/Uncertain ones stay pending/);
  });
});
