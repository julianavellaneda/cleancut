/**
 * The card's caution badges.
 *
 * The backend refuses to apply an unplaceable quote or an unevidenced filler
 * without a human, and now says which is which. The card is where that lands:
 * a badge in the header for the glance, and one sentence of explanation for
 * the reviewer who wants to know what to check. Both used to arrive smuggled
 * into `reasoning`, where they read as part of the model's own explanation.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ViolationCard } from "./ViolationCard";
import type { Violation } from "@/lib/api";

function violation(overrides: Partial<Violation> = {}): Violation {
  return {
    id: "v1",
    job_id: "job",
    text: "like",
    start_time: 1,
    end_time: 1.5,
    label: "Filler Word",
    rule_violated: null,
    severity: null,
    reasoning: "Detected common filler word 'like'.",
    status: "pending",
    action: "cut",
    is_approximate: false,
    is_ambiguous: false,
    ...overrides,
  };
}

function renderCard(v: Violation) {
  render(
    <ViolationCard
      violation={v}
      onAccept={vi.fn()}
      onReject={vi.fn()}
      onActionChange={vi.fn()}
      onPlayClip={vi.fn()}
      isUpdating={false}
    />
  );
}

describe("caution badges", () => {
  it("says nothing about a suggestion nobody doubted", () => {
    renderCard(violation());

    expect(screen.queryByText(/check before accepting/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/approximate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/check wording/i)).not.toBeInTheDocument();
  });

  it("marks an unplaced quote as approximate and says what to check", () => {
    renderCard(violation({ is_approximate: true }));

    expect(screen.getByText(/approximate/i)).toBeInTheDocument();
    expect(
      screen.getByText(/could not be matched to the transcript/i)
    ).toBeInTheDocument();
  });

  it("marks an unevidenced filler as one to check", () => {
    renderCard(violation({ is_ambiguous: true }));

    expect(screen.getByText(/check wording/i)).toBeInTheDocument();
    expect(screen.getByText(/also an ordinary word/i)).toBeInTheDocument();
  });

  it("shows both when both apply", () => {
    renderCard(violation({ is_approximate: true, is_ambiguous: true }));

    expect(screen.getByText(/approximate/i)).toBeInTheDocument();
    expect(screen.getByText(/check wording/i)).toBeInTheDocument();
  });

  it("leaves the model's reasoning to itself", () => {
    // The warning is a field now, so it must not be re-mixed into the one
    // block that is supposed to be the detector's own words.
    renderCard(violation({ is_approximate: true, reasoning: "an earnings claim" }));

    expect(screen.getByText("an earnings claim")).toBeInTheDocument();
  });
});
