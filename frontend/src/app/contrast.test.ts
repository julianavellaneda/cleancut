import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/*
 * The contrast audit, as a test rather than as a one-off measurement.
 *
 * Phase 1 fixed `--muted` by hand and Phase 7 fixed `--faint`, `--acc2` and
 * `--danger` the same way; nothing stopped the next edit to the token sheet
 * from undoing any of it. This parses `globals.css` itself - not a copy of the
 * values - so a token changed there is measured here.
 *
 * The thresholds are WCAG 2.1 AA: 4.5:1 for text, 3:1 for non-text UI
 * (borders, dots, the waveform). Which bar a token faces is a statement about
 * what it is *for*, so the two lists below are the real content of this file:
 * `--muted` is a text tier, `--faint` is not, and the four places that used
 * `--faint` for words were moved to `--muted` rather than the token loosened.
 */

type Rgba = [number, number, number, number];

const CSS = readFileSync(join(__dirname, "globals.css"), "utf8");

/**
 * The declarations in the block a selector opens.
 *
 * Brace-matched rather than sliced to the next `\n}`, because one of the three
 * blocks is nested inside a media query and would otherwise end early. The
 * selector must be followed by `{` to count: `:root:not([data-theme="light"])`
 * also appears inside `@custom-variant dark`, where it is part of a `:where()`
 * list and opens nothing.
 */
function tokensIn(selector: string): Record<string, string> {
  let from = 0;
  for (;;) {
    const at = CSS.indexOf(selector, from);
    if (at === -1) throw new Error(`no block opened by ${selector}`);
    const rest = CSS.slice(at + selector.length);
    const brace = rest.search(/\S/);
    if (rest[brace] !== "{") {
      from = at + selector.length;
      continue;
    }
    const open = at + selector.length + brace;
    let depth = 0;
    let close = open;
    for (let i = open; i < CSS.length; i++) {
      if (CSS[i] === "{") depth++;
      else if (CSS[i] === "}" && --depth === 0) {
        close = i;
        break;
      }
    }
    // Comments first: the notes above these tokens quote token names and
    // ratios ("--acc2: ... 3.95:1"), which the declaration regex would
    // otherwise read as a declaration and swallow the real one after it.
    const body = CSS.slice(open + 1, close).replace(/\/\*[\s\S]*?\*\//g, "");
    const out: Record<string, string> = {};
    for (const m of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      out[m[1]] = m[2].trim();
    }
    return out;
  }
}

function parse(value: string): Rgba {
  if (value.startsWith("#")) {
    const h = value.slice(1);
    return [
      parseInt(h.slice(0, 2), 16),
      parseInt(h.slice(2, 4), 16),
      parseInt(h.slice(4, 6), 16),
      1,
    ];
  }
  const parts = value.match(/rgba?\(([^)]+)\)/)?.[1].split(",").map(Number);
  if (!parts) throw new Error(`unparseable colour: ${value}`);
  return [parts[0], parts[1], parts[2], parts[3] ?? 1];
}

/** Composite a translucent foreground over an opaque ground. */
function flatten(fg: Rgba, bg: Rgba): Rgba {
  const a = fg[3];
  return [
    fg[0] * a + bg[0] * (1 - a),
    fg[1] * a + bg[1] * (1 - a),
    fg[2] * a + bg[2] * (1 - a),
    1,
  ];
}

function luminance([r, g, b]: Rgba): number {
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(fgToken: string, bgToken: string, tokens: Record<string, string>): number {
  const bg = parse(tokens[bgToken]);
  const fg = flatten(parse(tokens[fgToken]), bg);
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

/** Text on a ground: 4.5:1. */
const TEXT: Array<[string, string]> = [
  ["--text", "--bg"], ["--text", "--surface"], ["--text", "--surface2"],
  ["--muted", "--bg"], ["--muted", "--surface"], ["--muted", "--surface2"],
  // The tinted pills: label, severity, status, and the banner text.
  ["--acc-700", "--acc-100"], ["--acc-700", "--acc-200"], ["--acc-700", "--acc-300"],
  ["--acc2-700", "--acc2-100"], ["--acc2-700", "--acc2-200"], ["--acc2-700", "--acc2-300"],
  ["--danger-700", "--danger-100"],
  // Text on a solid accent fill: the primary, Download, Clean all and the
  // confirm-wipe buttons.
  ["--onacc", "--acc"], ["--onacc", "--acc-h"],
  ["--onacc", "--acc2"], ["--onacc", "--acc2-h"],
  ["--onacc", "--danger"],
];

/** Non-text UI - dots, borders, the waveform, swatches: 3:1. */
const NON_TEXT: Array<[string, string]> = [
  ["--faint", "--bg"], ["--faint", "--surface"], ["--faint", "--surface2"],
  ["--acc", "--bg"], ["--acc", "--surface"],
  ["--acc2", "--bg"], ["--acc2", "--surface"],
  ["--danger", "--bg"], ["--danger", "--surface"],
];

const THEMES = {
  light: ":root",
  "dark (explicit)": ':root[data-theme="dark"]',
  "dark (preference)": ':root:not([data-theme="light"])',
};

describe.each(Object.entries(THEMES))("%s theme", (_name, marker) => {
  const tokens = tokensIn(marker);

  it.each(TEXT)("%s on %s clears 4.5:1 for text", (fg, bg) => {
    expect(contrast(fg, bg, tokens)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(NON_TEXT)("%s on %s clears 3:1 for non-text UI", (fg, bg) => {
    expect(contrast(fg, bg, tokens)).toBeGreaterThanOrEqual(3);
  });
});

it("the two dark blocks define the same values", () => {
  // They are duplicated on purpose (an attribute block and a media query), so
  // the risk worth pinning is one being edited and the other left behind.
  expect(tokensIn(':root[data-theme="dark"]')).toEqual(
    tokensIn(':root:not([data-theme="light"])')
  );
});

it("--faint is never used as a text colour", () => {
  // The audit above only holds --faint to 3:1. That is only honest while no
  // component renders words in it.
  const src = join(__dirname, "..");
  const hits = execSync(
    `grep -rn "text-faint" --include='*.tsx' ${JSON.stringify(src)} || true`
  ).toString().trim();
  expect(hits).toBe("");
});
