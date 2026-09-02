/**
 * Formatting shared across screens.
 *
 * `formatDuration` exists because six components had grown their own copy of
 * the same four lines. This is the *duration* form - it rounds, because 59.6
 * seconds of audio is a minute long. A timestamp needs the flooring form, and
 * the panels that show timestamps still carry their own; they converge here
 * when the review panels are next touched.
 */
export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
