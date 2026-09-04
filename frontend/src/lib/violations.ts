import type { Violation } from "@/lib/api";

/** Labels produced by the deterministic scrubber - safe to bulk-accept. */
export const SCRUB_LABELS = ["Filler Word", "Dead Air"];

/**
 * How a suggestion is tinted, in one place because two panels have to agree.
 *
 * The label pill says *who* proposed the edit: the second accent for the
 * scrubber's measured findings, the first for the model's judgements. That is
 * the same split `Clean all` sweeps on, so the sidebar's bulk button and its
 * rows are colouring off one rule rather than two that could drift.
 */
export function labelTintClass(label: string | null): string {
  return label && SCRUB_LABELS.includes(label)
    ? "bg-acc2-100 text-acc2-700"
    : "bg-acc-200 text-acc-700";
}

/**
 * Severity as a word, not as a colour.
 *
 * The waveform used to carry severity in its region colours; it now carries
 * the *action*, which is what the export actually does. Severity did not stop
 * existing - it moved here, where it reads as a word and the colour is only
 * emphasis on top of the word.
 */
export function severityTextClass(severity: string | null): string {
  switch (severity?.toLowerCase()) {
    case "high":
      return "text-danger-700";
    case "medium":
      return "text-acc-700";
    default:
      return "text-muted";
  }
}

/** The accent a cut or a mute is drawn in, everywhere it is drawn. */
export function actionTextClass(action: string | null): string {
  return action?.toLowerCase() === "mute" ? "text-acc2" : "text-acc";
}

/**
 * The reasons the server refused to apply this one unreviewed, in the reviewer's
 * words rather than the column names.
 *
 * Rendered by the list as a single caution dot and by the detail panel as one
 * row each. They are read-only on every surface: `ViolationUpdate` deliberately
 * cannot carry them, so no client can talk the next sweep into a cut the
 * detector never stood behind.
 */
export function cautionFlags(v: Violation): { name: string; text: string }[] {
  const flags: { name: string; text: string }[] = [];
  if (v.is_approximate) {
    flags.push({
      name: "Approximate",
      text:
        "The quoted text could not be matched to the transcript, so this span " +
        "is the model's estimate rather than a measurement. Play the clip " +
        "before accepting.",
    });
  }
  if (v.is_ambiguous) {
    flags.push({
      name: "Check wording",
      text:
        `“${v.text}” is also an ordinary word, and nothing around it marks ` +
        "this instance as a hesitation. Cutting it may remove a real word.",
    });
  }
  return flags;
}
