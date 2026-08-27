/**
 * The re-analysis bar: prompt or preset, never a silent both.
 *
 * The analyzer runs in one mode or the other - a preset *replaces* the prompt
 * rather than refining it - so the form has to make the choice visible instead
 * of sending two fields and letting the backend pick. The submitted payload is
 * what these assert on, because that is where the mode is actually decided.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReanalyzeBar } from "./ReanalyzeBar";
import { api } from "@/lib/api";

beforeEach(() => {
  vi.spyOn(api, "listPresets").mockResolvedValue([
    { id: "pii-redaction", name: "PII Redaction", description: "" },
  ]);
});

function renderBar(props: Partial<React.ComponentProps<typeof ReanalyzeBar>> = {}) {
  const merged = {
    currentPrompt: "find income claims",
    currentPreset: null,
    isSubmitting: false,
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
    ...props,
  };
  render(<ReanalyzeBar {...merged} />);
  return merged;
}

it("starts from what was asked last time", () => {
  renderBar();

  expect(screen.getByLabelText(/Ask something else/)).toHaveValue("find income claims");
});

it("submits a trimmed prompt and no preset", async () => {
  const { onSubmit } = renderBar({ currentPrompt: null });

  await userEvent.type(screen.getByLabelText(/Ask something else/), "  find guarantees  ");
  await userEvent.click(screen.getByRole("button", { name: "Re-analyze" }));

  expect(onSubmit).toHaveBeenCalledWith({ prompt: "find guarantees" });
});

it("submits the preset alone once one is chosen", async () => {
  const { onSubmit } = renderBar();
  await waitFor(() => expect(screen.getByRole("option", { name: "PII Redaction" })).toBeInTheDocument());

  await userEvent.selectOptions(screen.getByLabelText("Rule preset"), "pii-redaction");
  await userEvent.click(screen.getByRole("button", { name: "Re-analyze" }));

  expect(onSubmit).toHaveBeenCalledWith({ preset: "pii-redaction" });
});

it("disables the prompt while a preset is selected", async () => {
  renderBar();
  await waitFor(() => expect(screen.getByRole("option", { name: "PII Redaction" })).toBeInTheDocument());

  await userEvent.selectOptions(screen.getByLabelText("Rule preset"), "pii-redaction");

  expect(screen.getByLabelText(/Ask something else/)).toBeDisabled();
});

it("will not submit an empty question", async () => {
  const { onSubmit } = renderBar({ currentPrompt: "   " });

  expect(screen.getByRole("button", { name: "Re-analyze" })).toBeDisabled();
  expect(onSubmit).not.toHaveBeenCalled();
});

it("says what a re-run will throw away before it is clicked", () => {
  renderBar();

  expect(screen.getByText(/replaces the current AI suggestions/)).toBeInTheDocument();
  expect(screen.getByText(/dead-air edits and your decisions on them are kept/)).toBeInTheDocument();
});

it("locks the form while the request is in flight", () => {
  renderBar({ isSubmitting: true });

  expect(screen.getByRole("button", { name: /Starting/ })).toBeDisabled();
  expect(screen.getByLabelText(/Ask something else/)).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
});

it("still renders when the preset list cannot be fetched", async () => {
  vi.spyOn(api, "listPresets").mockRejectedValue(new Error("offline"));
  const { onSubmit } = renderBar({ currentPrompt: "find guarantees" });

  await userEvent.click(screen.getByRole("button", { name: "Re-analyze" }));

  expect(onSubmit).toHaveBeenCalledWith({ prompt: "find guarantees" });
});
