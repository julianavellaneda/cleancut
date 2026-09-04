"use client";

import { useState } from "react";

import { PresetRadioGroup } from "@/components/PresetRadioGroup";
import { Button } from "@/components/ui/button";
import { Preset } from "@/lib/api";

interface ReanalyzeBarProps {
  /** What was asked the last time, shown so the change is a change from something. */
  currentPrompt: string | null;
  currentPreset: string | null;
  /**
   * The presets, fetched once by the page. Passed in rather than fetched here:
   * the header's meta line needs the same list to turn a preset id into a name,
   * and one screen making the same request twice is one too many.
   */
  presets: Preset[];
  /**
   * How many model suggestions the reviewer has already accepted - the exact
   * cost of the click, counted rather than alluded to.
   */
  acceptedModelCount: number;
  /** True while the request is in flight; the job's own status takes over after. */
  isSubmitting: boolean;
  onSubmit: (request: { prompt?: string; preset?: string }) => void;
  onCancel: () => void;
}

/**
 * Ask a different question about a recording that has already been transcribed.
 *
 * The card deliberately mirrors the upload screen's prompt/preset choice rather
 * than inventing a second vocabulary for the same thing - it is the same
 * question, asked again, down to sharing the `PresetRadioGroup`. What it does
 * not offer is auto-fix: a re-run's suggestions always come back pending,
 * because the reason to re-run is to look at them.
 *
 * The warning is not decoration. A re-analysis discards every model suggestion
 * including the accepted ones, and it says *how many* of those there are - the
 * page holds the number, and "including the 12 you've already accepted" is a
 * different sentence from "including any you have already accepted" when the
 * reviewer has spent twenty minutes on them.
 */
export function ReanalyzeBar({
  currentPrompt,
  currentPreset,
  presets,
  acceptedModelCount,
  isSubmitting,
  onSubmit,
  onCancel,
}: ReanalyzeBarProps) {
  const [prompt, setPrompt] = useState(currentPrompt ?? "");
  const [preset, setPreset] = useState<string | null>(currentPreset);

  const activePreset = presets.find(p => p.id === preset) ?? null;
  const usingPreset = preset !== null;
  const canSubmit = usingPreset || prompt.trim() !== "";

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit || isSubmitting) return;
    onSubmit(usingPreset ? { preset } : { prompt: prompt.trim() });
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Re-analyze this recording"
      className="flex flex-col gap-4 rounded-2xl bg-surface px-6 py-5"
    >
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="font-heading text-xl leading-tight">
          Ask something new about this transcript
        </h2>
        <span className="text-xs text-muted">
          re-reads the stored transcript — the audio is not transcribed again
        </span>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-[1.4fr_1fr]">
        <div className="relative">
          <textarea
            aria-label="Ask something new about this transcript"
            value={usingPreset ? "" : prompt}
            onChange={e => setPrompt(e.target.value)}
            disabled={usingPreset || isSubmitting}
            placeholder="e.g. flag anything that sounds like a guarantee"
            className="min-h-24 w-full resize-y rounded-[20px] border border-divider bg-bg px-4 py-3 text-sm leading-normal caret-acc transition-colors focus:border-acc"
          />
          {/*
            The same overlay the upload screen uses, for the same reason:
            dimming says the control is unavailable without saying why, and the
            why is the one thing needed to get the textarea back.
          */}
          {activePreset && (
            <div className="absolute inset-0 grid place-items-center rounded-[20px] bg-bg/[0.92] p-4 text-center text-[13px] text-muted text-pretty">
              <span>
                The <strong className="font-semibold text-acc2-700">{activePreset.name}</strong>{" "}
                rulebook will drive this analysis.
              </span>
            </div>
          )}
        </div>

        <PresetRadioGroup
          presets={presets}
          value={preset}
          onChange={setPreset}
          disabled={isSubmitting}
        />
      </div>

      <div className="flex items-center gap-3 rounded-lg bg-bg px-4 py-3 text-[13px] text-pretty">
        <span
          aria-hidden
          className="grid size-[30px] flex-none place-items-center rounded-full bg-danger-100 font-bold text-danger-700"
        >
          !
        </span>
        <span>
          Re-analysis{" "}
          <strong className="font-bold">
            discards every model suggestion
            {acceptedModelCount > 0 && <> — including the {acceptedModelCount} you&apos;ve already accepted</>}
          </strong>
          . Filler-word and dead-air suggestions and your decisions on them are kept.
        </span>
      </div>

      <div className="flex justify-end gap-2.5">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canSubmit || isSubmitting}>
          {isSubmitting ? "Starting…" : "Re-analyze and discard"}
        </Button>
      </div>
    </form>
  );
}
