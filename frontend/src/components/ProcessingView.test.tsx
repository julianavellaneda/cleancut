/**
 * The processing screen: what the pipeline is doing, per stage.
 *
 * The value here is the stage *arithmetic*, not the styling. Which stages
 * apply depends on the upload (only AIFF is converted, only a pre-accepting
 * job exports) and where the job sits depends on a status string that has to
 * line up with `services/worker.py`. A restyle cannot break either, but an
 * edit to `stageStates` silently can - and did nothing to catch itself, since
 * this component had no tests at all before it was redesigned.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProcessingView } from "./ProcessingView";
import { Job } from "@/lib/api";

function job(overrides: Partial<Job> = {}): Job {
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
    duration_seconds: 125,
    language: "en",
    created_at: new Date().toISOString(),
    error_message: null,
    export_status: "none",
    export_error: null,
    edit_revision: 0,
    export_revision: null,
    violation_count: 0,
    pending_count: 0,
    accepted_count: 0,
    rejected_count: 0,
    ...overrides,
  };
}

/** The state label sits in the row for its stage, so read it from there. */
function stateOf(label: string): string {
  const row = screen.getByText(label).closest("li") as HTMLElement;
  return within(row).getByText(
    /^(done|running|waiting|skipped|not required)$/,
  ).textContent as string;
}

it("names the recording and how it is being analyzed", () => {
  render(<ProcessingView job={job({ duration_seconds: 125 })} />);

  expect(screen.getByRole("heading", { name: "seminar.mp3" })).toBeInTheDocument();
  expect(screen.getByText("Audio · 2:05 · prompt mode")).toBeInTheDocument();
});

describe("where the job has got to", () => {
  it("marks the stages behind it done and the ones ahead waiting", () => {
    render(<ProcessingView job={job({ status: "transcribing" })} />);

    expect(stateOf("Transcribing")).toBe("running");
    expect(stateOf("Analyzing")).toBe("waiting");
    expect(stateOf("Ready to review")).toBe("waiting");
  });

  it("skips the stages this upload will not reach", () => {
    // Only AIFF is transcoded, and the worker only exports up front when it
    // has something pre-accepted to export.
    render(<ProcessingView job={job({ original_filename: "seminar.mp3", auto_fix: false })} />);

    expect(stateOf("Converting")).toBe("skipped");
    // "not required" rather than "skipped": nothing went wrong, there was
    // simply nothing to render yet.
    expect(stateOf("Exporting")).toBe("not required");
  });

  it("keeps the stages an AIFF upload with auto-fix on will actually walk", () => {
    render(
      <ProcessingView
        job={job({ original_filename: "seminar.aiff", auto_fix: true, status: "converting" })}
      />,
    );

    expect(stateOf("Converting")).toBe("running");
    expect(stateOf("Exporting")).toBe("waiting");
  });
});

it("says a queued job has not started, rather than showing a stage running", () => {
  // `pending` is not one of the stage ids, so nothing may claim to be running:
  // the worker has not picked the job up at all.
  render(<ProcessingView job={job({ status: "pending" })} />);

  expect(
    screen.getByText(/Queued — waiting for the worker to pick this up/),
  ).toBeInTheDocument();
  expect(screen.queryByText("running")).not.toBeInTheDocument();
  expect(stateOf("Transcribing")).toBe("waiting");
});

it("tells the reader the page moves on its own", () => {
  render(<ProcessingView job={job()} />);

  // Without this the screen looks stuck, and a reader reloads it by hand.
  expect(screen.getByText(/checks for progress every 2 seconds/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /All recordings/ })).toHaveAttribute("href", "/");
});
