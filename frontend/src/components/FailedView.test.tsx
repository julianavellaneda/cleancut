/**
 * The failed-job screen.
 *
 * The thing worth pinning is that the server's reason is actually *rendered*.
 * The alternative this replaced - the review UI with nothing in it - reads as
 * a clean recording rather than as a job that never ran, and that failure is
 * silent in exactly the way the project's analysis paths are careful not to be.
 */

import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { FailedView } from "./FailedView";
import { Job } from "@/lib/api";

function job(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    filename: "job-1.mp3",
    original_filename: "seminar.mp3",
    media_type: "audio",
    prompt: "flag income claims",
    status: "failed",
    auto_fix: false,
    auto_scrub: false,
    preset: null,
    duration_seconds: 125,
    language: null,
    created_at: new Date().toISOString(),
    error_message: "ffmpeg exited with code 1: Invalid data found when processing input",
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

it("names the recording and shows what the server said", () => {
  render(<FailedView job={job()} />);

  expect(screen.getByRole("heading", { name: "seminar.mp3" })).toBeInTheDocument();
  expect(screen.getByText("This recording could not be processed.")).toBeInTheDocument();
  expect(
    screen.getByText(/ffmpeg exited with code 1: Invalid data found when processing input/),
  ).toBeInTheDocument();
});

it("leaves the reason block out when the server gave none", () => {
  // An empty "What the server said" panel claims the server answered and said
  // nothing, which is a different fact from having no message stored.
  render(<FailedView job={job({ error_message: null })} />);

  expect(screen.queryByText("What the server said")).not.toBeInTheDocument();
});

it("offers a way back", () => {
  render(<FailedView job={job()} />);

  const links = screen.getAllByRole("link");
  expect(links.length).toBeGreaterThan(0);
  for (const link of links) expect(link).toHaveAttribute("href", "/");
});
