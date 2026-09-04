import { useId } from "react";

/**
 * The CleanCut mark: a violet disc with a single light bar cut through it at a
 * slight angle - the edit, made into the logo.
 *
 * Drawn as an SVG rather than the mockup's positioned-div-inside-overflow-hidden
 * trick, so it scales, prints, and cannot be clipped wrongly by a parent. The
 * bar is filled with `--bg`, so it reads as a gap in the disc in both themes
 * rather than as a white stripe painted on top.
 */
export function CleanCutMark({ size = 34, className }: { size?: number; className?: string }) {
  // The clip path is referenced by id, so two marks on one page must not share
  // one - `useId` is what keeps a second instance from being clipped by the
  // first's path.
  const clipId = useId();

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 34 34"
      className={className}
      aria-hidden
      focusable="false"
    >
      <defs>
        <clipPath id={clipId}>
          <circle cx="17" cy="17" r="17" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`}>
        <circle cx="17" cy="17" r="17" fill="var(--acc)" />
        <rect
          x="12"
          y="-5"
          width="6"
          height="44"
          rx="3"
          fill="var(--bg)"
          transform="rotate(18 17 17)"
        />
      </g>
    </svg>
  );
}
