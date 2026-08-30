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
import { api } from "@/lib/api";

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
