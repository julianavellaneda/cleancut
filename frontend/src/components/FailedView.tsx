"use client";

import Link from "next/link";

import { ArrowLeftGlyph } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Job } from "@/lib/api";

/**
 * A failed job has no violations and no waveform worth showing, so the review
 * screen would render as an empty one - which reads as a clean recording
 * rather than as a job that never ran. This says what happened instead.
 *
 * Extracted from the review page rather than left inline: it shares nothing
 * with the review state that page holds, and lifting it out is what keeps that
 * file readable before the layout work lands on it.
 *
 * The server's message goes in a `<pre>` under its own kicker. It is often a
 * stack trace or an ffmpeg line, and the one thing a reader must be able to do
 * with it is copy it somewhere useful - so it keeps its whitespace and its
 * monospace face rather than being reflowed into the prose above it.
 */
export function FailedView({ job }: { job: Job }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-8 py-16">
      <div className="flex w-full max-w-[640px] flex-col gap-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 self-start text-[13px] text-muted no-underline transition-colors hover:text-acc"
        >
          <ArrowLeftGlyph size={13} />
          All recordings
        </Link>

        <div className="flex items-start gap-4.5">
          <div className="grid size-13 flex-none place-items-center rounded-full bg-danger-100 font-heading text-[26px] text-danger-700">
            <span aria-hidden>!</span>
          </div>
          <div className="min-w-0">
            <h1 className="mb-1.5 font-heading text-[30px] leading-tight [overflow-wrap:anywhere]">
              {job.original_filename || job.filename}
            </h1>
            <p className="text-[15px] text-muted">This recording could not be processed.</p>
          </div>
        </div>

        {job.error_message && (
          <div className="rounded-lg bg-surface px-5 py-4">
            <div className="mb-2 text-[11px] uppercase tracking-[0.08em] text-muted">
              What the server said
            </div>
            <pre className="m-0 max-h-[280px] overflow-auto font-mono text-[12.5px]/[1.55] whitespace-pre-wrap [overflow-wrap:anywhere]">
              {job.error_message}
            </pre>
          </div>
        )}

        <Button asChild size="sm" className="self-start">
          <Link href="/">Back to recordings</Link>
        </Button>
      </div>
    </div>
  );
}
