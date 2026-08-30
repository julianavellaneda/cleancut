/**
 * The review screen's keyboard contract.
 *
 * Reviewing eighty filler words by mouse is the bottleneck this UI exists to
 * remove, so the bindings are the feature - and until now the only record of
 * them was `KeyboardLegend`'s list and a comment. These pin the documented
 * contract: `J`/`K` (and the arrows) move, `A`/`R` decide *and advance*, `M`
 * toggles cut/mute, `Space` is the transport, `P` plays the selected clip, `T`
 * the transcript, `?` the legend.
 *
 * The three guards matter more than the bindings themselves, because each one
 * is a key doing something destructive at a moment the user meant something
 * else: a modifier combination is a browser shortcut, a keystroke in a text
 * field is text, and `Space` on a focused `<button>` is that button - the
 * transcript's lines are buttons, so without the last guard clicking a line
 * with the keyboard also toggled playback.
 *
 * The Waveform is mocked, but as a real `forwardRef` exposing the three
 * `WaveformHandle` methods as spies: the page drives playback through that
 * handle, so a plain `<div>` mock would let `Space` and `P` "pass" by calling
 * nothing at all.
 */

import { forwardRef, useImperativeHandle } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "./page";
import { api, Job, Transcript, Violation } from "@/lib/api";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "job-1" }),
}));

const waveform = vi.hoisted(() => ({
  playClip: vi.fn(),
  togglePlayPause: vi.fn(),
  seekTo: vi.fn(),
}));

vi.mock("@/components/Waveform", () => ({
  Waveform: forwardRef<typeof waveform, Record<string, unknown>>(
    function MockWaveform(_props, ref) {
      useImperativeHandle(ref, () => waveform, []);
      return <div data-testid="waveform" />;
    }
  ),
}));

function violation(overrides: Partial<Violation> = {}): Violation {
  return {
    id: "v1",
    job_id: "job-1",
    text: "um",
    start_time: 1,
    end_time: 2,
    label: "Filler Word",
    rule_violated: null,
    severity: "low",
    reasoning: "reason one",
    status: "pending",
    action: "cut",
    is_approximate: false,
    is_ambiguous: false,
    ...overrides,
  };
}

// Three suggestions, each identified by its reasoning: only the card renders
// that, so it says which row is *selected* rather than which rows exist.
const violations: Violation[] = [
  violation({ id: "v1", reasoning: "reason one", start_time: 1, end_time: 2 }),
  violation({ id: "v2", reasoning: "reason two", start_time: 10, end_time: 12 }),
  violation({ id: "v3", reasoning: "reason three", start_time: 20, end_time: 21 }),
];

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    filename: "job-1.mp3",
    original_filename: "seminar.mp3",
    media_type: "audio",
    prompt: "find filler words",
    status: "completed",
    auto_fix: false,
    auto_scrub: false,
    preset: null,
    duration_seconds: 60,
    language: "en",
    created_at: "2026-01-01T00:00:00",
    error_message: null,
    export_status: "none",
    export_error: null,
    edit_revision: 0,
    export_revision: null,
    violation_count: 3,
    pending_count: 3,
    accepted_count: 0,
    rejected_count: 0,
    ...overrides,
  };
}

const transcript: Transcript = {
  job_id: "job-1",
  language: "en",
  duration: 60,
  segments: [
    { start: 0, end: 5, text: "Welcome to the seminar." },
    { start: 10, end: 15, text: "Last month I made eleven thousand dollars." },
  ],
};

/** The reasoning of the suggestion the detail card is currently showing. */
async function selected(): Promise<string> {
  const card = await screen.findByText(/^reason (one|two|three)$/);
  return card.textContent ?? "";
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(api, "getJob").mockResolvedValue(job());
  vi.spyOn(api, "getViolations").mockResolvedValue(violations);
  vi.spyOn(api, "getTranscript").mockResolvedValue(null);
  vi.spyOn(api, "getAudioUrl").mockReturnValue("http://example.test/audio");
  vi.spyOn(api, "updateViolation").mockImplementation(
    async (_jobId, violationId, update) => ({
      ...violations.find(v => v.id === violationId)!,
      ...update,
    } as Violation)
  );
});

/** Render and wait for the review UI, with the first suggestion selected. */
async function renderReview() {
  render(<ReviewPage />);
  await waitFor(() => expect(screen.getByTestId("waveform")).toBeInTheDocument());
  await waitFor(async () => expect(await selected()).toBe("reason one"));
}

describe("moving through the list", () => {
  it("advances on J and on ArrowDown, and goes back on K and ArrowUp", async () => {
    await renderReview();

    await userEvent.keyboard("j");
    expect(await selected()).toBe("reason two");

    await userEvent.keyboard("{ArrowDown}");
    expect(await selected()).toBe("reason three");

    await userEvent.keyboard("k");
    expect(await selected()).toBe("reason two");

    await userEvent.keyboard("{ArrowUp}");
    expect(await selected()).toBe("reason one");
  });

  it("clamps at both ends rather than wrapping or clearing the selection", async () => {
    await renderReview();

    // Past the top: a wrap here would jump the reviewer to the last suggestion,
    // and an unclamped index would leave the card showing nothing. The press
    // counts are deliberately not multiples of the list length - three presses
    // against three suggestions land back on the first either way, so they
    // would pass against a wrap.
    await userEvent.keyboard("kk");
    expect(await selected()).toBe("reason one");

    await userEvent.keyboard("jjjj");
    expect(await selected()).toBe("reason three");
  });
});

describe("deciding with the keyboard", () => {
  it("accepts on A and moves to the next suggestion", async () => {
    await renderReview();

    await userEvent.keyboard("a");

    await waitFor(() =>
      expect(api.updateViolation).toHaveBeenCalledWith("job-1", "v1", { status: "accepted" })
    );
    // The advance is the whole point: deciding from the buttons leaves the
    // reviewer where they clicked, deciding from the keyboard moves on.
    await waitFor(async () => expect(await selected()).toBe("reason two"));
  });

  it("rejects on R and moves on too", async () => {
    await renderReview();

    await userEvent.keyboard("r");

    await waitFor(() =>
      expect(api.updateViolation).toHaveBeenCalledWith("job-1", "v1", { status: "rejected" })
    );
    await waitFor(async () => expect(await selected()).toBe("reason two"));
  });

  it("stays on the last suggestion after deciding it", async () => {
    await renderReview();

    await userEvent.keyboard("jj");
    expect(await selected()).toBe("reason three");

    await userEvent.keyboard("a");

    await waitFor(() =>
      expect(api.updateViolation).toHaveBeenCalledWith("job-1", "v3", { status: "accepted" })
    );
    expect(await selected()).toBe("reason three");
  });

  it("toggles cut and mute on M, without moving the selection", async () => {
    await renderReview();

    await userEvent.keyboard("m");

    await waitFor(() =>
      expect(api.updateViolation).toHaveBeenCalledWith("job-1", "v1", { action: "mute" })
    );
    expect(await selected()).toBe("reason one");

    await userEvent.keyboard("m");

    await waitFor(() =>
      expect(api.updateViolation).toHaveBeenLastCalledWith("job-1", "v1", { action: "cut" })
    );
  });

  it("does not stack a second PATCH on top of one still in flight", async () => {
    // A held-down "a" is the realistic way this happens: the decision keys are
    // gated on isUpdating precisely so a repeat cannot overlap.
    vi.spyOn(api, "updateViolation").mockReturnValue(new Promise(() => {}));

    await renderReview();

    await userEvent.keyboard("a");
    await waitFor(() => expect(api.updateViolation).toHaveBeenCalledTimes(1));
    await userEvent.keyboard("a");

    expect(api.updateViolation).toHaveBeenCalledTimes(1);
  });
});

describe("playback", () => {
  it("toggles play/pause on Space", async () => {
    await renderReview();

    await userEvent.keyboard(" ");

    expect(waveform.togglePlayPause).toHaveBeenCalledTimes(1);
  });

  it("plays the selected clip on P, with that suggestion's span", async () => {
    await renderReview();

    await userEvent.keyboard("j");
    expect(await selected()).toBe("reason two");

    await userEvent.keyboard("p");

    expect(waveform.playClip).toHaveBeenCalledWith(10, 12);
  });
});

describe("the panels", () => {
  it("toggles the transcript on T", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript);

    await renderReview();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Transcript" })).toBeInTheDocument()
    );
    expect(screen.queryByPlaceholderText("Search the transcript…")).not.toBeInTheDocument();

    await userEvent.keyboard("t");
    expect(screen.getByPlaceholderText("Search the transcript…")).toBeInTheDocument();

    await userEvent.keyboard("t");
    expect(screen.queryByPlaceholderText("Search the transcript…")).not.toBeInTheDocument();
  });

  it("toggles the shortcut legend on ?", async () => {
    await renderReview();
    expect(screen.getByRole("button", { name: /Keyboard shortcuts/ })).toBeInTheDocument();

    await userEvent.keyboard("?");
    expect(screen.getByText("Accept and advance")).toBeInTheDocument();

    await userEvent.keyboard("?");
    expect(screen.queryByText("Accept and advance")).not.toBeInTheDocument();
  });
});

describe("the guards", () => {
  it("ignores a key held with a modifier", async () => {
    await renderReview();

    // Cmd-A is select-all and Ctrl-R is reload; neither is a decision about a
    // suggestion, and both used to be one.
    await userEvent.keyboard("{Meta>}a{/Meta}");
    await userEvent.keyboard("{Control>}r{/Control}");
    await userEvent.keyboard("{Alt>}j{/Alt}");

    expect(api.updateViolation).not.toHaveBeenCalled();
    expect(await selected()).toBe("reason one");
  });

  it("ignores keys typed into a text field", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript);

    await renderReview();
    await userEvent.keyboard("t");

    const search = screen.getByPlaceholderText("Search the transcript…");
    await userEvent.click(search);
    // Every letter here is also a binding: searching for "a jar" must not
    // accept an edit, jump the selection, or close the panel it was typed into.
    await userEvent.type(search, "a jar");

    expect(search).toHaveValue("a jar");
    expect(api.updateViolation).not.toHaveBeenCalled();
    expect(await selected()).toBe("reason one");
    expect(screen.getByPlaceholderText("Search the transcript…")).toBeInTheDocument();
  });

  it("leaves Space to a focused button, so activating one does not also toggle playback", async () => {
    vi.spyOn(api, "getTranscript").mockResolvedValue(transcript);

    await renderReview();
    await userEvent.keyboard("t");

    const line = screen.getByRole("button", { name: /Welcome to the seminar/ });
    line.focus();
    await userEvent.keyboard(" ");

    // The browser's activate-on-space fired: the panel seeked to that line.
    expect(waveform.seekTo).toHaveBeenCalledWith(0);
    expect(waveform.togglePlayPause).not.toHaveBeenCalled();
  });

  it("does nothing while the job is still in the pipeline", async () => {
    // There is nothing to review yet, so every binding is inert. Note this
    // holds for two reasons at once - the handler is not bound below
    // `completed`, and there are no suggestions to act on either way - so it
    // pins the behaviour rather than the `job.status` check specifically.
    vi.spyOn(api, "getJob").mockResolvedValue(job({ status: "transcribing" }));

    render(<ReviewPage />);
    await waitFor(() => expect(screen.queryByText(/Loading/)).not.toBeInTheDocument());
    expect(screen.queryByTestId("waveform")).not.toBeInTheDocument();

    await userEvent.keyboard("a j p ?");

    expect(api.updateViolation).not.toHaveBeenCalled();
    expect(waveform.playClip).not.toHaveBeenCalled();
    expect(waveform.togglePlayPause).not.toHaveBeenCalled();
  });
});
