/**
 * Formatting shared across screens.
 *
 * Two forms of the same clock, and the difference matters. `formatDuration`
 * **rounds**, because 59.6 seconds of audio is a minute long. `formatTimestamp`
 * **floors**, because a marker at 59.6s is still in the 0:59 second and a
 * reader scrubbing to 1:00 would land past it. Six components had grown their
 * own copy of one or the other; the review panels were the last holdouts.
 */
export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function formatTimestamp(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
