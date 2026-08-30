/**
 * The sidebar's two bulk affordances.
 *
 * "Clean All" is a sweep over the scrubber's own suggestions, and until
 * recently it was one-way: a reviewer who hit it and changed their mind had no
 * bulk route back. The undo button only appears while a sweep is standing, and
 * the count on Clean All has to describe what the click will actually do -
 * pending scrubber edits, not every scrubber edit and not every pending one.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ViolationList } from "./ViolationList";
import type { Violation } from "@/lib/api";

let seq = 0;

function violation(overrides: Partial<Violation> = {}): Violation {
  seq += 1;
  return {
    id: `v${seq}`,
    job_id: "job",
    text: "um",
    start_time: seq,
    end_time: seq + 0.5,
    label: "Filler Word",
    rule_violated: null,
    severity: null,
    reasoning: null,
    status: "pending",
    action: "cut",
    is_approximate: false,
    is_ambiguous: false,
    ...overrides,
  };
}

function renderList(props: Partial<React.ComponentProps<typeof ViolationList>> = {}) {
  const defaults = {
    violations: [] as Violation[],
    selectedViolation: null,
    onSelect: vi.fn(),
    onCleanAll: vi.fn(),
    onUndoCleanAll: vi.fn(),
    canUndoCleanAll: false,
    isCleaning: false,
  };
  const merged = { ...defaults, ...props };
  render(<ViolationList {...merged} />);
  return merged;
}

describe("Clean All", () => {
  it("counts only the pending scrubber edits", () => {
    renderList({
      violations: [
        violation(),
        violation({ label: "Dead Air" }),
        violation({ status: "accepted" }),          // already decided
        violation({ label: "Income Claims" }),      // the LLM's, not the scrubber's
      ],
    });

    expect(screen.getByRole("button", { name: /Clean All \(2\)/ })).toBeInTheDocument();
  });

  it("is hidden when there is nothing left to sweep", () => {
    renderList({ violations: [violation({ status: "accepted" })] });

    expect(screen.queryByRole("button", { name: /Clean All/ })).not.toBeInTheDocument();
  });

  it("does not offer to sweep the analyst's own suggestions", () => {
    renderList({ violations: [violation({ label: "Income Claims" })] });

    expect(screen.queryByRole("button", { name: /Clean All/ })).not.toBeInTheDocument();
  });
});

describe("Undo Clean All", () => {
  it("is absent until a sweep has run", () => {
    renderList({ violations: [violation()] });

    expect(screen.queryByRole("button", { name: /Undo/ })).not.toBeInTheDocument();
  });

  it("appears once a sweep is standing, even with nothing left pending", () => {
    renderList({ violations: [violation({ status: "accepted" })], canUndoCleanAll: true });

    expect(screen.getByRole("button", { name: /Undo Clean All/ })).toBeInTheDocument();
  });

  it("calls back when clicked", async () => {
    const { onUndoCleanAll } = renderList({
      violations: [violation({ status: "accepted" })],
      canUndoCleanAll: true,
    });

    await userEvent.click(screen.getByRole("button", { name: /Undo Clean All/ }));

    expect(onUndoCleanAll).toHaveBeenCalledOnce();
  });

  it("is disabled while a bulk move is in flight", () => {
    renderList({
      violations: [violation(), violation({ status: "accepted" })],
      canUndoCleanAll: true,
      isCleaning: true,
    });

    expect(screen.getByRole("button", { name: /Undo Clean All/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Cleaning/ })).toBeDisabled();
  });
});

describe("the list itself", () => {
  it("selects the edit that was clicked", async () => {
    const rows = [violation({ text: "um" }), violation({ text: "uh" })];
    const { onSelect } = renderList({ violations: rows });

    await userEvent.click(screen.getByText(/uh/));

    expect(onSelect).toHaveBeenCalledWith(rows[1]);
  });

  it("marks the rows the detector was unsure about", () => {
    // The glance half of the two flags. Without it an auto_fix job's sidebar
    // is a list of accepted rows with a few pending ones in it and no visible
    // reason why those few were held back.
    renderList({
      violations: [
        violation({ text: "um" }),
        violation({ text: "like", is_ambiguous: true }),
        violation({ text: "quit your job", is_approximate: true }),
      ],
    });

    expect(screen.getByLabelText(/ordinary word/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/could not be matched/i)).toBeInTheDocument();
  });

  it("says so when the analysis came back with nothing", () => {
    renderList({ violations: [] });

    expect(screen.getByText("No edits suggested")).toBeInTheDocument();
  });
});
