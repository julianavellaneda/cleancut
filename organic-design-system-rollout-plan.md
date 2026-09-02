# Organic design system rollout

Adopting the design in `Organic design system mockups/CleanCut.dc.html` across the CleanCut
frontend. Seven phases, each one session, each ending on a green suite.

## Decisions taken up front

| Question | Decision |
|---|---|
| Palette | **The mockup's own tokens**, not `_ds/styles.css`. Lavender ground `#efecf8`, violet accent `#6a57c9`, blue second accent `#4a7bc4`, `--danger:#c15c66`, plus the dark set the mockup already defines. The `_ds` "Organic" folder is the *parent* system (cream/terracotta); `CleanCut.dc.html` re-tokenised it for this app and every screen was composed against those values — the cut/mute region colours in particular were picked to read on lavender. |
| Review layouts | **`list-left` only.** The mockup's three-way segmented control (List left / Waveform top / Detail first) is not built. The grid is still expressed as `grid-template-areas`, so the other two are a later additive change, not a rewrite. |
| Dark mode | **Both themes.** `prefers-color-scheme` by default, overridable by an explicit toggle that persists. |
| Fonts | **Self-hosted**, `next/font/local`, per the existing convention and `test_docker_layout.py`. Caprasimo (display) + Figtree (body), both SIL OFL. Geist Mono is **kept** — the mockup uses `ui-monospace` for timestamps and the file is already committed. |

The mockup's fixed bottom-right **demo strip** (Home / Queued / Processing / … / theme dot) is a
mockup navigation affordance. Not built. The theme toggle it carries moves into the real header.

## What the mockup actually changes

It is not a recolour. Four things change *structurally*, and they are where the risk is:

1. **Controls change element type.** The preset `<select>` becomes a list of pill radio buttons;
   the two `<input type="checkbox">` become toggle switches. Both are queried by the existing
   tests through their accessible names, so both need real ARIA roles rather than styled `<div>`s.
2. **The review page changes layout mechanism** — a flex row of fixed-width `<aside>`s becomes a
   CSS grid with named areas, so the transcript column opening reflows the whole page rather than
   squeezing the middle.
3. **Waveform regions change what they encode.** Today the region colour is keyed off
   `severity` (red/yellow/grey). The mockup keys it off **`action`** — cut is a solid violet
   band, mute is a blue hatch — with `status` carried in opacity. That is a semantics change:
   severity moves to a text badge in the list and detail panels, where it reads as a word.
4. **`window.confirm` goes away** on the admin page, replaced by a themed modal.

Everything else is styling.

## Cross-cutting rules for every phase

- **Never hard-code a colour.** Every value comes from a `var(--…)` defined in `globals.css`.
  A phase that introduces a literal hex outside that file has failed its own review.
- **Copy changes break tests.** The suite queries by accessible name and visible text, never by
  class (verified — no `toHaveClass` anywhere). So a restyle alone breaks nothing, and a reworded
  button breaks exactly one assertion. Each phase below lists the assertions it must move; update
  them **in the same commit**, never by loosening a matcher to `/.*/`.
- **Contrast.** The mockup's `--muted` is `rgba(30,28,43,.58)` on the lavender ground — that is
  fine for meta text at 12–13px only if it clears 4.5:1. Measure it in Phase 1 and darken the
  token there if it does not, rather than patching per-site later.
- **Reduced motion.** The mockup adds three keyframe animations (`cc-pulse`, `cc-spin`,
  `cc-breathe`). All three go behind `@media (prefers-reduced-motion: reduce)` in Phase 1,
  alongside the existing `stage-sweep` rule which already does this.
- **Each phase ends green**: `npm test`, `npx tsc --noEmit`, `npm run lint`, `npm run build`, and
  `pytest backend/tests/test_docker_layout.py`.

---

## Phase 0 — Preflight (30 min, can fold into Phase 1)

Not a code phase. Confirm before starting:

- `npm test && npx tsc --noEmit && npm run lint && npm run build` is green **today**, so a later
  failure is unambiguously ours.
- Fetch the two font faces. Caprasimo and Figtree both ship under the SIL Open Font License.
  Download the woff2 files and their `OFL.txt`, and commit them — a `next build` must stay
  network-free. This is the only phase that needs the network.
- Note the `frontend/src/app/api/` directory is currently untracked in git alongside other
  in-flight work; the design rollout touches none of it.

---

## Phase 1 — Foundation: tokens, fonts, theme

The whole app recolours in one step and every screen keeps working. No layout moves yet.

**`src/app/globals.css`** — replace the shadcn oklch block with the mockup's token sheet.

```
:root                        → light tokens (--bg, --surface, --surface2, --text, --muted,
                               --faint, --divider, --acc, --acc-h, --acc-100/200/300/700,
                               --acc2 + ramp, --danger + 100/700, --onacc, --shadow-sm/md/lg)
:root[data-theme="dark"]     → dark tokens
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) → dark tokens
}
```

Three blocks, not two — the media query alone cannot be overridden by a toggle in both
directions. Keep the `@theme inline` bridge so Tailwind utilities (`bg-surface`, `text-muted`,
`rounded-lg`) resolve to the new variables; that is what keeps the untouched screens compiling
while later phases convert them one at a time.

Also here: `--radius` scale (14 / 18 / 24 / 28 / 32px — the mockup over-rounds and uses several),
the four keyframes, the reduced-motion block, `::selection`, and `:focus-visible { outline: 2px
solid var(--acc); outline-offset: 2px }`.

**`src/app/layout.tsx`** — swap `Geist-Variable` for `Figtree` on `--font-body` and add
`Caprasimo` as `--font-heading`. Keep `GeistMono-Variable` on `--font-mono`. Delete the footer —
the mockup has none; its Admin link moves to the home header as "Maintenance" in Phase 2 (add it
to the home header in this phase so the route stays reachable in between).

**No-flash theme script.** An inline `<script>` in `<head>` that reads `localStorage` and stamps
`data-theme` before first paint. Without it, a dark-mode user gets a lavender flash on every
navigation. It must be inline and synchronous; a `useEffect` is too late.

**`src/components/ThemeToggle.tsx`** — new. Reads/writes `localStorage`, stamps the attribute,
and starts from `prefers-color-scheme` when nothing is stored. Guard the storage access in
try/catch — a browser with site data blocked must still render.

**`src/components/ui/{button,card,badge}.tsx`** — restyle the variants in place rather than
deleting them. Keeping the component API means Phases 2–6 change markup, not call signatures.

- `button`: `rounded-full` throughout. `default` → `bg-[--acc] text-[--onacc]` in **Caprasimo**
  (the mockup sets primary buttons in the display face — this is the single most characteristic
  detail of the design). `outline` → `1px solid var(--divider)`, transparent, hover `--surface`.
  `ghost` → transparent, hover tint. Add a `pill-sm` size for the 13px chrome buttons.
- `card`: `--surface` fill, `border-radius: 28px`, **no border** — the mockup separates by fill,
  never by hairline. Drop the shadow at rest.
- `badge`: the pill used for status/label/severity, tinted from the ramps.

`ui/{progress,scroll-area}.tsx` are untouched here; check in Phase 5 whether the redesign still
uses them, and delete them (with the `radix-ui` dep, if nothing else needs it) if not.

**Tests to move:** `backend/tests/test_docker_layout.py::test_frontend_build_fetches_no_fonts_over_the_network`
asserts `Geist-Variable.woff2` and `GeistMono-Variable.woff2` exist. Update it to the new face
list and keep the `next/font/google` prohibition exactly as it is — that assertion is the point
of the test.

**Done when:** every screen renders in the new palette, light and dark, with nothing relaid out.
Expect it to look unfinished — square-ish cards in violet. That is correct for this phase.

---

## Phase 2 — Home screen

`src/app/page.tsx` (326 lines) plus one or two extracted components.

**Header.** The CleanCut mark (a violet circle with a rotated light bar cut through it — an SVG
component, not a background trick), 38px Caprasimo wordmark, the strapline, and "Maintenance"
pushed right.

**"New edit" card.** A 32px-radius `--surface` panel holding a 1.4fr/1fr grid:

- *Instructions* textarea, 20px radius, `--bg` fill, `--divider` border, accent caret. When a
  preset is active the mockup overlays it at 92% opacity with a sentence naming the preset,
  rather than dimming it to 50% as today — the reason it is disabled becomes readable.
- *Rule preset* — the `<select>` becomes a column of pill buttons, each with a custom radio dot.
  **Build it as a real `radiogroup`**: a `<fieldset>` with `role="radiogroup"` and an accessible
  name of "Rule preset", options as `role="radio"` + `aria-checked`, arrow-key navigation. A "None
  — use my instructions" option must survive; the mockup omits it because its demo always has one.
- The two **toggle switches**. `<button role="switch" aria-checked>` carrying the same accessible
  names as the current labels, so the existing queries survive with a role change. Each gets the
  mockup's one-line explanation under the title — copy those verbatim; they state the
  "uncertain ones stay pending" contract that `worker._is_pre_accepted` actually implements.
- **Drop zone** — 26px dashed, an accent circle with the upload glyph, and the format list.
- **Upload state list** and the **error banner** (a `--danger-100` pill with a dismiss ×).

**Recordings list.** Per row: a 44px circle carrying an audio-wave or film glyph by
`media_type`, filename, a meta line `duration · mode · N suggestions`, a status pill (pulsing
while unfinished), and a Review / Details button. Then `Showing N of N · newest first`.

`mode` is `preset ? "<Preset name> preset" : "prompt"` — it needs the preset list the page
already fetches, so map the id to its name rather than printing the slug.

**Tests to move (`src/app/page.test.tsx`, 251 lines):**

| Assertion | Change |
|---|---|
| `getByLabelText("Rule preset")` | now names a radiogroup |
| `getByRole("option", { name: "Income Claims" })` | → `getByRole("radio", …)` |
| `getByRole("option", { selected: true })` | → `getByRole("radio", { checked: true })` |
| `getByLabelText("Auto-apply markers")` / `("Scrubber mode")` | still resolve; assert `role="switch"` and `aria-checked` |
| `getByLabelText(/Instructions/)` | unchanged |

Add coverage for the preset-active overlay and for keyboard traversal of the radiogroup.

---

## Phase 3 — Processing and Failed screens

Small phase, deliberately — it is a good place to absorb Phase 2 overrun.

**`src/components/ProcessingView.tsx`** (195 lines) already has the right shape: a stage list with
connector rails and per-stage state labels. This is mostly a restyle — Caprasimo 19px stage
titles, 14px dots with a 2px ring, `cc-pulse` on the running one, uppercase state labels right.
Two additions from the mockup: the **queued banner** ("waiting for the worker to pick this up —
no stage has started yet") shown while `status === "pending"`, and the footer line naming the
2-second poll interval. Keep the existing `stage-sweep` treatment or drop it in favour of the
dot pulse; do not run both.

**`src/components/FailedView.tsx`** — new, extracted from the `job.status === "failed"` branch
inlined in `jobs/[id]/page.tsx`. The mockup gives it a composed layout: a 52px `--danger-100`
circle with a Caprasimo `!`, the filename as an `h1`, and the server's message in a monospace
`<pre>` under a "What the server said" kicker. Extracting it shortens the review page before
Phase 4 touches it, which is the real reason to do it here.

---

## Phase 4 — Review shell

`src/app/jobs/[id]/page.tsx` (541 lines). Chrome and layout only; the three panels stay as they
are and get restyled in Phase 5. Splitting the file this way is what keeps both phases reviewable.

**Header.** A 38px circular back button (arrow glyph, `title="All recordings"`), the job name
truncating with its meta line, then the right cluster: Transcript and New prompt pills carrying
their `<kbd>` hints, the theme toggle, and the export control. Export is a violet Caprasimo
button that becomes a **blue** `--acc2` download link once ready — the colour change is the
signal that the artefact exists.

**Three banners**, in the mockup's order: export-failed (`--danger-100`, with an inline Retry),
dismissable error, and the "Heads up" warning (`--acc2-100`) that carries `job.error_message` on
a completed job. All three already exist; they are re-skinned, and the amber Tailwind literals in
the current warning banner go away with them.

**The grid.**

```
cols:  360px 1fr                    areas: "list media"
                                           "list detail"

with transcript open:
cols:  340px 1fr 320px              areas: "list media transcript"
                                           "list detail transcript"
```

`gap: 16px`, `align-items: start`, list and transcript capped at `calc(100vh - 150px)` and
scrolling internally. Below ~1100px this must collapse to a single column — the mockup does not
say what happens on a narrow viewport, so: media, then list, then detail, with the transcript
becoming an overlay rather than a third column.

**`ReanalyzeBar.tsx`** (107 lines) → the mockup's card: the heading with its "re-reads the stored
transcript — the audio is not transcribed again" note, the prompt/preset split reusing Phase 2's
radiogroup, and the discard warning stating the **count** of already-accepted LLM suggestions that
will be lost. That count is a genuine improvement over the current wording and the page already
holds the data to compute it.

**Tests to move:** `page.test.tsx` and `ReanalyzeBar.test.tsx` — `getByRole("button", { name:
"Transcript" })` survives; the reanalyze copy assertions
(`/replaces the current AI suggestions/`, `/dead-air edits and your decisions on them are kept/`)
move to the mockup's wording. `keyboard.test.tsx` (360 lines) should need **no** change — it
mocks `Waveform` as a `forwardRef` and drives `window` events, neither of which this phase
touches. If it does break, that is a signal the restyle changed behaviour and should be
investigated, not patched.

---

## Phase 5 — Review panels (the largest phase)

Four components. If it runs long, the natural split is Waveform alone in a Phase 5b — it is the
only one with real logic in it.

**`ViolationList.tsx`** (188 lines). Rows become a `44px 1fr auto` grid: mono start time, then a
label pill + severity word + a `!` caution dot for `is_approximate`/`is_ambiguous`, then the
quoted text (struck through when accepted-and-cut), then the action word over a decision dot
(outlined = pending, filled = accepted, faint = rejected). Header: "N suggestions", the decision
summary, and Clean all / Undo as accent-2 pills.

**`ViolationCard.tsx`** (238 lines). The detail panel: label pill, severity, `i of N`, the rule
line, the timestamp range with its duration — then the quote as a **24px Caprasimo blockquote**,
which is the panel's whole visual idea. Reasoning below in `--muted`. The review flags render as
`--danger-100` rows with an uppercase name and the sentence, one per flag. Footer: the cut/mute
segmented control under an "On export" kicker (each option carrying its consequence —
"shortens" / "keeps timing"), Play clip with its `P` hint, and Accept/Reject with `A`/`R`.

Keep the flags rendering strictly one-way — `ViolationUpdate` must not gain them, for the reason
CLAUDE.md gives.

**`TranscriptPanel.tsx`** (124 lines). Search input in the header, rows as `40px 1fr` with a 3px
left border tinted by the covering edit's action, the current line lifted to `--bg`, cut lines
struck through, and a small uppercase action tag. Empty state: `No lines match "…"`.

**`Waveform.tsx`** (289 lines) — the one with real work.

- Colours move to tokens read from the computed style rather than the four literals at
  `Waveform.tsx:120-122` and in `getActionColor` at `:266`.
- **Theme reactivity**: WaveSurfer takes its colours at construction. On a theme flip, call
  `setOptions({ waveColor, progressColor, cursorColor })` and repaint the regions — do **not**
  rebuild the instance, which would re-fetch and re-decode the audio.
- **Regions re-key from severity to action**: cut = solid `--acc`, mute = a
  `repeating-linear-gradient` hatch in `--acc2`, with status carried in opacity. The legend row
  under the transport spells this out, so it is discoverable rather than folkloric.
- **The transport bar is now ours**: −5s / play-pause / +5s circular buttons, a mono readout, a
  "loading audio…" spinner while `duration === 0`, and the legend. Every control keeps the
  `duration === 0` guard that `Waveform.test.tsx` already pins.
- The **export-ready strip** (`--acc2-100`, play button, "N edits applied · Ns removed",
  progress, duration) replaces the bare `<audio controls>`.

**`KeyboardLegend.tsx`** (68 lines) → the fixed bottom-centre pill that expands into a shortcut
bar. Nine entries; the collapsed state shows `J K A R step through · ? all shortcuts`.

**Tests to move:** `ViolationCard.test.tsx`, `ViolationList.test.tsx`, `Waveform.test.tsx` (419
lines — the arithmetic assertions survive; only colour expectations move),
`TranscriptPanel`'s `getByPlaceholderText("Search the transcript…")` loses its ellipsis, and
`getByText("Accept and advance")` becomes `"Accept"`. `getByRole("button", { name: /Clean All
\(2\)/ })` becomes `/Clean all 2/`.

---

## Phase 6 — Admin

`src/app/admin/page.tsx` (134 lines). Smallest screen, most caution.

Three stat cards on `--surface` with 30px Caprasimo values and skeleton/error states; the admin
token as a pill password input with its "kept only in this browser" note; the irreversible
actions as rows with a danger-outlined button each and an inline result line.

**`window.confirm` at `admin/page.tsx:37` is replaced by the mockup's modal** — a 32px card over
a `rgba(20,18,36,.5)` backdrop, with a danger circle, `"<Action>?"` as the title, the consequence
sentence, and **`Keep everything` as the cancel** (the mockup's wording, and better than
"Cancel": the safe option states what it does). Build it as a `<dialog>` or an
`aria-modal` div with a focus trap, Escape to close, and focus landing on the cancel button.

Per the stored note *"Admin wipe hits real dirs"*: **do not smoke-test these against a running
server.** Verify the modal with unit tests and a mocked API client only.

---

## Phase 7 — Polish and verification

- **Contrast audit** across both themes: `--muted` and `--faint` on `--bg` and on `--surface`,
  the accent on its own ramp tints, and the `--danger-700` on `--danger-100` pairing.
- **Keyboard pass**: every interactive element reachable, focus ring visible on both grounds, the
  radiogroups and the admin modal behaving.
- **Reduced-motion pass**: confirm all four animations are actually suppressed.
- **Visual verification** with the `playwright-cli` skill (already installed — never install a
  browser) at 1440px, 1100px and 700px, both themes, across all five screens.
- Refresh the README screenshot, which currently shows the old review interface.
- **Update `CLAUDE.md` and `GEMINI.md`** — the frontend Conventions section still describes
  shadcn/Tailwind defaults, and `GEMINI.md` has drifted before. Record the token sheet as the
  single owner of colour, and the action-keyed region semantics.

---

## Risk register

| Risk | Where | Mitigation |
|---|---|---|
| Waveform colours frozen at construction | Phase 5 | `setOptions` on theme change; never rebuild the instance |
| Region semantics change loses severity | Phase 5 | Severity moves to a text badge in list + detail; it stops being a colour, it does not stop existing |
| Toggle/radio restyle drops accessible names | Phase 2 | Real `role="switch"` / `role="radiogroup"`; the existing `getByLabelText` queries are the regression test |
| Dark-mode flash on navigation | Phase 1 | Synchronous inline `<head>` script, before first paint |
| `next build` starts fetching fonts | Phase 1 | Self-host; `test_docker_layout.py` already pins this — update the filenames, keep the assertion |
| Contrast regressions from `--muted` at .58 alpha | Phase 1 | Measure in Phase 1 and fix the token, not the call sites |
| Grid has no narrow-viewport answer | Phase 4 | Single-column collapse specified above; the mockup is silent, so this is our decision to make and document |
| Admin wipes tested live | Phase 6 | Mocked API only — stored memory says these hit real directories |

## Suggested commit shape

One commit per phase, message naming the behaviour rather than the styling — the repo's existing
history reads that way ("A built frontend was pinned to whichever backend built it").
