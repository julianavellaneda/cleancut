/**
 * The redesign's line glyphs, at the mockup's 2.75 stroke weight.
 *
 * They are components rather than inline SVG at each call site because several
 * appear on more than one screen, and because `currentColor` plus a single
 * stroke width is the whole reason they look like one family. Every one is
 * `aria-hidden`: each sits next to text that already says what it means, so a
 * screen reader announcing it twice is noise.
 */

type GlyphProps = { size?: number; className?: string };

function Glyph({ size = 18, className, children }: GlyphProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
      className={className}
    >
      {children}
    </svg>
  );
}

export function AudioGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M2 13a2 2 0 0 0 2-2V7a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0V4a2 2 0 0 1 4 0v13a2 2 0 0 0 4 0v-4a2 2 0 0 1 2-2" />
    </Glyph>
  );
}

export function VideoGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="m16 13 5.2 3.1a.5.5 0 0 0 .8-.4V8.3a.5.5 0 0 0-.8-.4L16 11" />
      <rect x="2" y="6" width="14" height="12" rx="3" />
    </Glyph>
  );
}

export function UploadGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M12 3v12" />
      <path d="m7 8 5-5 5 5" />
      <path d="M5 21h14" />
    </Glyph>
  );
}

export function RefreshGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M21 12a9 9 0 1 1-3-6.7" />
      <path d="M21 3v6h-6" />
    </Glyph>
  );
}

export function ArrowLeftGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="m12 19-7-7 7-7" />
      <path d="M19 12H5" />
    </Glyph>
  );
}

export function DownloadGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M12 3v12" />
      <path d="m17 10-5 5-5-5" />
      <path d="M5 21h14" />
    </Glyph>
  );
}

/*
 * The two transport glyphs are *filled*, not stroked, so they sit apart from
 * the line family above: a play triangle drawn in 2.75px outline at 16px is a
 * smudge, and these are the only glyphs that ever appear inside a solid accent
 * button where a fill is what reads.
 */
export function PlayGlyph({ size = 16, className }: GlyphProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="currentColor"
      aria-hidden focusable="false" className={className}
    >
      <path d="M7 4.5v15l12-7.5z" />
    </svg>
  );
}

export function PauseGlyph({ size = 16, className }: GlyphProps) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="currentColor"
      aria-hidden focusable="false" className={className}
    >
      <rect x="5" y="4" width="5" height="16" rx="1.5" />
      <rect x="14" y="4" width="5" height="16" rx="1.5" />
    </svg>
  );
}

/** The skip pair: `RefreshGlyph` mirrored, so the two read as one control. */
export function SkipBackGlyph(props: GlyphProps) {
  return (
    <Glyph {...props}>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 3v6h6" />
    </Glyph>
  );
}

// The forward skip is the same circular arrow as `RefreshGlyph`, aliased
// rather than redrawn: the two never share a screen, and one path is one path.
export const SkipForwardGlyph = RefreshGlyph;
