"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Preset, api } from "@/lib/api";

interface ReanalyzeBarProps {
  /** What was asked the last time, shown so the change is a change from something. */
  currentPrompt: string | null;
  currentPreset: string | null;
  /** True while the request is in flight; the job's own status takes over after. */
  isSubmitting: boolean;
  onSubmit: (request: { prompt?: string; preset?: string }) => void;
  onCancel: () => void;
}

/**
 * Ask a different question about a recording that has already been transcribed.
 *
 * The bar deliberately mirrors the upload screen's prompt/preset choice rather
 * than inventing a second vocabulary for the same thing - it is the same
 * question, asked again. What it does not offer is auto-fix: a re-run's
 * suggestions always come back pending, because the reason to re-run is to look
 * at them.
 *
 * The warning about replacing the current suggestions is not decoration. A
 * re-analysis discards every LLM suggestion including the accepted ones, and
 * that is worth saying before the click rather than after.
 */
export function ReanalyzeBar({
  currentPrompt,
  currentPreset,
  isSubmitting,
  onSubmit,
  onCancel,
}: ReanalyzeBarProps) {
  const [prompt, setPrompt] = useState(currentPrompt ?? "");
  const [preset, setPreset] = useState(currentPreset ?? "");
  const [presets, setPresets] = useState<Preset[]>([]);

  useEffect(() => {
    api.listPresets().then(setPresets).catch(() => setPresets([]));
  }, []);

  const usingPreset = preset !== "";
  const canSubmit = usingPreset || prompt.trim() !== "";

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;
    onSubmit(usingPreset ? { preset } : { prompt: prompt.trim() });
  }

  return (
    <form
      onSubmit={submit}
      className="border-b bg-surface2/30 px-8 py-4"
      aria-label="Re-analyze this recording"
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-3">
        <div className="flex items-baseline justify-between gap-4">
          <label htmlFor="reanalyze-prompt" className="text-xs font-bold uppercase tracking-widest text-muted-foreground">
            Ask something else
          </label>
          <span className="text-xs text-muted-foreground">
            No re-transcription — this re-reads the stored transcript.
          </span>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="reanalyze-prompt"
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            disabled={usingPreset || isSubmitting}
            placeholder="e.g. flag anything that sounds like a guarantee"
            className="flex-1 rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          />
          <select
            aria-label="Rule preset"
            value={preset}
            onChange={e => setPreset(e.target.value)}
            disabled={isSubmitting}
            className="rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">Prompt mode</option>
            {presets.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <Button type="submit" size="sm" disabled={!canSubmit || isSubmitting}>
            {isSubmitting ? "Starting…" : "Re-analyze"}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
        </div>

        <p className="text-xs text-muted-foreground">
          This replaces the current AI suggestions, including any you have already accepted.
          Filler-word and dead-air edits and your decisions on them are kept.
        </p>
      </div>
    </form>
  );
}
