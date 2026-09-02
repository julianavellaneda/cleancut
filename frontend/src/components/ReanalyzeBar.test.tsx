/**
 * The re-analysis card: prompt or preset, never a silent both.
 *
 * The analyzer runs in one mode or the other - a preset *replaces* the prompt
 * rather than refining it - so the form has to make the choice visible instead
 * of sending two fields and letting the backend pick. The submitted payload is
 * what these assert on, because that is where the mode is actually decided.
 *
 * The preset list now arrives as a prop rather than being fetched here: the
 * review page needs the same list for its header, and one screen making the
 * same request twice is one too many.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ReanalyzeBar } from "./ReanalyzeBar";

const PRESETS = [{ id: "pii-redaction", name: "PII Redaction", description: "" }];

const question = () => screen.getByLabelText("Ask something new about this transcript");

function renderBar(props: Partial<React.ComponentProps<typeof ReanalyzeBar>> = {}) {
  const merged = {
    currentPrompt: "find income claims",
    currentPreset: null,
    presets: PRESETS,
    acceptedModelCount: 0,
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

  expect(question()).toHaveValue("find income claims");
});

it("submits a trimmed prompt and no preset", async () => {
  const { onSubmit } = renderBar({ currentPrompt: null });

  await userEvent.type(question(), "  find guarantees  ");
  await userEvent.click(screen.getByRole("button", { name: "Re-analyze and discard" }));

  expect(onSubmit).toHaveBeenCalledWith({ prompt: "find guarantees" });
});

it("submits the preset alone once one is chosen", async () => {
  const { onSubmit } = renderBar();

  await userEvent.click(screen.getByRole("radio", { name: "PII Redaction" }));
  await userEvent.click(screen.getByRole("button", { name: "Re-analyze and discard" }));

  expect(onSubmit).toHaveBeenCalledWith({ preset: "pii-redaction" });
});

it("names the preset that has taken the prompt's place", async () => {
  renderBar();

  await userEvent.click(screen.getByRole("radio", { name: "PII Redaction" }));

  expect(question()).toBeDisabled();
  expect(screen.getByText(/rulebook will drive this analysis/)).toBeInTheDocument();
});

it("goes back to prompt mode from a preset, with the question intact", async () => {
  // Selecting a preset hides the prompt behind the overlay rather than
  // clearing it, so changing your mind does not cost you what you typed.
  const { onSubmit } = renderBar({ currentPreset: "pii-redaction" });

  expect(screen.getByRole("radio", { checked: true })).toHaveAccessibleName("PII Redaction");

  await userEvent.click(screen.getByRole("radio", { name: /None/ }));

  expect(question()).toHaveValue("find income claims");

  await userEvent.click(screen.getByRole("button", { name: "Re-analyze and discard" }));

  expect(onSubmit).toHaveBeenCalledWith({ prompt: "find income claims" });
});

it("will not submit an empty question", async () => {
  const { onSubmit } = renderBar({ currentPrompt: "   " });

  expect(screen.getByRole("button", { name: "Re-analyze and discard" })).toBeDisabled();
  expect(onSubmit).not.toHaveBeenCalled();
});

it("counts the accepted suggestions a re-run would throw away", () => {
  renderBar({ acceptedModelCount: 12 });

  expect(screen.getByText(/including the 12 you've already accepted/)).toBeInTheDocument();
  expect(
    screen.getByText(/Filler-word and dead-air suggestions and your decisions on them are kept/)
  ).toBeInTheDocument();
});

it("does not offer a count when there is nothing accepted to lose", () => {
  renderBar({ acceptedModelCount: 0 });

  expect(screen.getByText(/discards every model suggestion/)).toBeInTheDocument();
  expect(screen.queryByText(/already accepted/)).not.toBeInTheDocument();
});

it("locks the form while the request is in flight", () => {
  renderBar({ isSubmitting: true });

  expect(screen.getByRole("button", { name: /Starting/ })).toBeDisabled();
  expect(question()).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
});

it("still offers prompt mode when the preset list could not be fetched", async () => {
  const { onSubmit } = renderBar({ presets: [], currentPrompt: "find guarantees" });

  await userEvent.click(screen.getByRole("button", { name: "Re-analyze and discard" }));

  expect(onSubmit).toHaveBeenCalledWith({ prompt: "find guarantees" });
});
