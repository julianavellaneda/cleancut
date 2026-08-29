# CleanCut — Redesign Context Reference

Factual inventory of the product as currently built. No recommendations.

---

## 1. What the product does

Upload an audio or video recording plus a plain-English instruction (or a rule preset). The backend
transcribes it with word-level timestamps, sends the transcript + instruction to an LLM, maps the
LLM's quoted text back onto word timings, and stores each match as a **Violation** (a suggested
edit). The user reviews suggestions on a waveform, accepts or rejects each one, chooses **cut** or
**mute** per edit, and exports a re-rendered file via a single FFmpeg pass.

Stated philosophy: "Copilot, not Autopilot" — nothing is removed without a human accepting it.

Product name: **CleanCut**. Tagline in `layout.tsx` metadata: "Describe what to find in plain
English, review it on a waveform, export a surgically edited file."

Note: the domain object is named `Violation` in the API and DB, but user-facing copy calls these
"Suggested Edits", "edits", or "Markers" (admin screen). Both vocabularies exist in the codebase.

---

## 2. Tech stack (frontend)

| Item | Value |
|---|---|
| Framework | Next.js 16.3.3, App Router, all pages `"use client"` |
| React | 19.2.3 |
| Styling | Tailwind v4 (`@import "tailwindcss"`), CSS-variable theme in `globals.css` |
| Component layer | shadcn-style local primitives in `components/ui/` built on `radix-ui` + `class-variance-authority` |
| Waveform | `wavesurfer.js` ^7.12.1 + its Regions plugin |
| Fonts | `Geist` (`--font-body`) and `Geist_Mono` (`--font-mono`) via `next/font/google` |
| Icons | `lucide-react` is installed but **not imported anywhere** — the UI currently uses text/emoji glyphs (`←`, `▶`, `✓`, `✗`) |
| Utility | `cn()` = `clsx` + `tailwind-merge` |

### Theme tokens (`globals.css`)

All colors are OKLCH and **fully achromatic** (chroma 0) except `--destructive`. There is no brand
hue in the system today.

Light (`:root`): `--background: oklch(1 0 0)`, `--foreground: oklch(0.145 0 0)`,
`--primary: oklch(0.205 0 0)`, `--muted: oklch(0.97 0 0)`,
`--muted-foreground: oklch(0.556 0 0)`, `--border`/`--input`: `oklch(0.922 0 0)`,
`--ring: oklch(0.708 0 0)`, `--destructive: oklch(0.577 0.245 27.325)` (red),
`--radius: 0.5rem`.

Dark (`.dark`): background `oklch(0.145 0 0)`, foreground `oklch(0.985 0 0)`, primary inverted to
near-white, `--secondary`/`--muted`/`--accent`/`--border`/`--input` all `oklch(0.269 0 0)`,
`--destructive: oklch(0.396 0.141 25.723)`.

Full token set: background, foreground, card, card-foreground, popover, popover-foreground,
primary, primary-foreground, secondary, secondary-foreground, muted, muted-foreground, accent,
accent-foreground, destructive, destructive-foreground, border, input, ring, radius.

**Dark mode is defined but has no toggle** — `.dark` is never applied by any component, and there
is no theme provider. Dark styles are only reachable by manually adding the class.

One custom animation exists: `@keyframes stage-sweep` (2.6s, `cubic-bezier(0.45,0,0.55,1)`,
infinite, translateX -110% → 510%), exposed as `.animate-stage-sweep`, with a
`prefers-reduced-motion: reduce` branch that freezes it at `translateX(180%)`.

### Primitive variants available

- **Button** — variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link`.
  Sizes: `default` (h-9), `xs` (h-7), `sm` (h-8), `lg` (h-10), `icon` (size-9). Radius `rounded-md`.
- **Badge** — variants: `default`, `secondary`, `destructive`, `outline`, `ghost`. `rounded-md`,
  `text-xs`.
- **Card** — `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`.
  Content padding `p-6`.
- **ScrollArea** / **ScrollBar** — Radix-based.
- **Progress** — Radix-based, defined but **not used by any screen** (the processing view draws its
  own bars).

---

## 3. Routes / screens

There are exactly **three** routes plus a persistent global footer.

| Route | File | Purpose |
|---|---|---|
| `/` | `app/page.tsx` | Upload + instruction/preset selection + recent projects list |
| `/jobs/[id]` | `app/jobs/[id]/page.tsx` | Review interface (also renders processing and failed states) |
| `/admin` | `app/admin/page.tsx` | Stats + destructive maintenance actions |

### Global shell (`app/layout.tsx`)

`<body>` is `min-h-screen flex flex-col`. A `<main class="flex-grow">` wraps the page, and a
**footer on every route**: `p-8 border-t text-center text-xs text-muted-foreground`, containing
`© 2026 AI Media Editor` and an `/admin` link, centered with `gap-6`.

Note: the footer is a normal document-flow element, but `/jobs/[id]` renders an `h-screen`
container, so on the review screen the footer sits below the fold, pushing total document height
past the viewport.

---

## 4. Screen: `/` — Upload

Container: `max-w-4xl mx-auto py-12 px-6 space-y-12`.

**Header** — `h1` "CleanCut" (`text-3xl font-bold tracking-tight`) + muted subtitle "Describe what
to find in plain English. Review it on a waveform. Export a surgically edited file."

**Card "Create New Edit"** contains, top to bottom:

1. **Instructions textarea** — label "Instructions", `min-h-[100px]`, placeholder
   `"E.g., Remove filler words and silences..."`.
   *Preset interaction:* when a preset is selected the textarea is **disabled**, its value forced to
   `""`, opacity 50, placeholder swaps to `"The {name} rulebook is driving this analysis."`, and the
   label appends `(disabled — {name} preset active)`.
2. **Rule preset `<select>`** — only rendered if `presets.length > 0`. First option is
   `"None — use my instructions"`, then one option per preset (`name` as the text). When active, the
   select gets `border-primary bg-primary/5` and a helper line below shows the preset's
   `description` + "The custom prompt is ignored while a preset is selected."
3. **Two checkboxes** in a `grid md:grid-cols-2 gap-4`, each a bordered clickable label row:
   - "Auto-apply markers" → `auto_fix`
   - "Scrubber mode" → `auto_scrub`
   Neither has any explanatory text in the UI.
4. **Dropzone** — `border-2 border-dashed rounded-lg p-12 text-center`, click-to-browse (hidden
   `<input type="file" multiple>`). Idle copy: "Drop media files here" / "or click to browse local
   storage". Dragging state: `border-primary bg-primary/5`. Uploading state: the whole zone becomes
   `"Processing Upload..."` with `animate-pulse` and `pointer-events-none opacity-50`.
5. **Error line** — `text-xs text-destructive text-center` under the dropzone.

**Client-side file filter:** `/\.(mp3|wav|m4a|flac|ogg|webm|aif|aiff|mp4|mov)$/i`. Files failing it
produce the message `"Invalid file format."` Multiple files are accepted and uploaded
**sequentially in a loop**, one job created per file.

**Recent Projects list** — rendered only when `jobs.length > 0`. Section header
"RECENT PROJECTS" (`text-sm font-semibold uppercase tracking-wider text-muted-foreground`) with a
ghost `REFRESH` button. Each row: bordered card, filename (`original_filename || filename`,
truncated) over a `10px` uppercase line reading `{m:ss duration} — {status}`. Right side is a
"Review" button when `status === "completed"`, otherwise the status string in pulsing uppercase.
Duration renders `-` when `duration_seconds` is null.

**Known gap:** per-file `uploadProgress` state ("Uploading..." / "Queued" / "Failed", cleared after
5 s) is tracked but **never rendered anywhere** in the JSX.

**Polling:** `setInterval` every **3000 ms** calling `GET /api/jobs`; starts on mount and after any
upload, stops when no job has a status outside `completed`/`failed`.

---

## 5. Screen: `/jobs/[id]` — three distinct states

The route branches into four renders: loading, processing, failed, review.

### 5a. Loading
Full-screen centered `Loading…` in muted small text.

### 5b. Processing — `components/ProcessingView.tsx`

Rendered whenever status is not `completed`/`failed`. Centered column, `max-w-2xl`, `space-y-10`.

- **Title**: filename, `text-2xl font-semibold tracking-tight truncate`.
- **Meta line**: joined with ` · ` from — `"Video"` or `"Audio"`; formatted duration (omitted if
  null); and `"{preset} preset"` / `"prompt mode"` / omitted.
- **Queued block** (only when no stage is active, i.e. status `pending`): the word "Queued", a 3px
  sweeping bar, and "Waiting for a worker to pick this recording up".
- **Vertical stepper** (`<ol>`) with a connecting rail. Five fixed stages, always all rendered:

  | id | Label | Active caption |
  |---|---|---|
  | `converting` | Converting | "Transcoding the upload to a format Whisper can read" |
  | `transcribing` | Transcribing | "Listening to the recording and timing every word" |
  | `analyzing` | Analyzing | "Reading the transcript against your instructions" |
  | `exporting` | Exporting | "Rendering the pre-accepted edits" |
  | `completed` | Ready to review | (none) |

  Per-stage state is one of `done` / `active` / `pending` / `skipped`, drawn as a 12px dot:
  done = filled; active = filled + `ring-4 ring-foreground/15`; skipped = bordered w/ muted fill;
  pending = bordered outline. Right-aligned status word: `"done"`, `"skipped"`, or for the export
  stage `"not required"`; active and pending stages show nothing.
  The active stage additionally shows the sweeping 3px bar + its caption.

  **Applicability rules encoded in the UI:** the `converting` stage is marked `skipped` unless the
  filename matches `/\.aiff?$/i`; the `exporting` stage is marked `not required` unless
  `auto_fix || auto_scrub` is set.
- **Footer line**: "This page updates on its own. You can leave it open."

### 5c. Failed
Full-screen centered: heading "Processing failed", the sentence
`"{filename} could not be processed."`, the raw `error_message` in a `<pre>` (bordered,
`bg-muted/40`, wrapped, `text-xs`) when present, and a "Back to Projects" button.

### 5d. Review (the main workspace)

Layout: `h-screen flex flex-col`.

**Header bar** (`border-b px-8 py-4`, space-between):
- Left: `← Projects` link + filename `h1` (`text-lg font-bold`, `truncate max-w-md`).
- Right: a single button. Before export it reads "Export Edited" (or "Exporting..."), and is
  **disabled when zero violations have `status === "accepted"`**. After a successful export it is
  replaced by "Download Master", which opens the download URL in a new window.

**Partial-analysis banner** (conditional, when `job.error_message` is set on a completed job): full
width `border-b border-amber-500/40 bg-amber-500/10 px-8 py-3 text-xs`, amber text, prefixed with a
bold uppercase "PARTIAL ANALYSIS —". This is the only amber/warning color in the app, and it is
hardcoded (not a theme token).

**Body**: `flex-1 flex overflow-hidden`, two columns.

**Left sidebar** — fixed `w-80`, `border-r bg-muted/20`, `components/ViolationList.tsx`:
- Header block: `"Suggested Edits ({count})"`.
- **"Clean All (N)"** button — secondary, full width, only rendered when N > 0, where N counts
  violations that are `pending` **and** whose label is in `SCRUB_LABELS = ["Filler Word", "Dead Air"]`.
  Tooltip: "Accept every pending filler word and dead-air edit". Bulk-accepts those labels, then
  disappears.
- Scrollable list. Empty state: "No edits suggested".
- Each row shows: `m:ss` start time (mono, 10px, left) — then right-aligned a `✓`/`✗` glyph when not
  pending, a severity badge (uppercase, only if severity present), and an action badge. Below:
  the label (or `"Suggested Edit"` fallback), truncated; then the quoted `text` in italic 10px,
  clamped to one line.
- Selected row: `bg-accent border-accent-foreground/20`; others `border-transparent hover:bg-muted`.

**Right main column** — split into an upper media panel and a lower detail panel.

*Upper panel* (`p-8 border-b bg-muted/10`, inner `max-w-4xl mx-auto`):
- If `media_type === "video"`: a `<video controls>` at `aspect-video`, black bg, `mb-8`. Wavesurfer
  is then bound to that element via the `media` option rather than loading audio itself.
- **Waveform** (`components/Waveform.tsx`): 100px tall, `barWidth: 2`, `barGap: 1`, `barRadius: 2`,
  `waveColor "#94a3b8"`, `progressColor "#334155"`, `cursorColor "#1e293b"`, `cursorWidth 2`.
  These four colors are **hardcoded hex, not theme tokens**, so the waveform does not follow
  light/dark.
  Region overlay colors, also hardcoded:

  | Condition | Fill |
  |---|---|
  | status `rejected` | `rgba(148,163,184,0.1)` (slate, faintest) |
  | status `accepted` | `rgba(148,163,184,0.2)` (slate) |
  | pending + action `cut` | `rgba(239,68,68,0.15)` (red) |
  | pending + action `mute` | `rgba(234,179,8,0.15)` (yellow) |
  | fallback | `rgba(148,163,184,0.2)` |

  Regions are non-draggable and non-resizable; clicking one selects that violation.
  Controls row below the canvas: `-5s` (outline sm), `Play`/`Pause` (secondary, `size="lg"`,
  `w-16`), `+5s` (outline sm) on the left; `m:ss / m:ss` mono timecode on the right. All disabled
  until wavesurfer fires `ready`.
  Selecting a violation seeks the playhead to `start_time - 0.2s`.
  `playClip` seeks to `start - 0.5s`, plays, and pauses via `setTimeout` after
  `(end + 0.5 - start)` seconds.
- **Result player** (only after a successful export): a bordered box labeled "RESULT"
  (10px bold uppercase tracking-widest) containing a `<video>` or `<audio>` element pointed at the
  export stream URL.

*Lower panel* (`flex-1 p-8 overflow-auto`, inner `max-w-2xl mx-auto`) — `components/ViolationCard.tsx`:
- Empty states: "No edits suggested for this recording" (zero violations) or "Select an edit to
  review".
- Card header: label as `text-xl font-bold` title (fallback "Suggested Edit"), plus severity badge
  and a **clickable action badge that toggles cut↔mute**.
- Body sections, in order, each conditional:
  - "RULE VIOLATED" + value (preset mode only)
  - Mono timecode `m:ss — m:ss`, then the quoted `text` in italic inside `bg-muted/50 rounded-md p-4`
  - "REASONING" + text inside `bg-primary/5 rounded-md border`
  - "Status:" + badge (`Accepted` default variant / `Rejected` outline variant), shown only when not
    pending
- Footer action block (`pt-6 border-t mt-auto`):
  - "ON EXPORT" row with two segmented buttons, `Cut` and `Mute`; the current one is `default`
    variant, the other `outline`. (This duplicates the header badge toggle.)
  - `▶ Play Clip` — full-width outline button
  - If pending: `Accept` (default, flex-1) + `Reject` (outline, flex-1, destructive text)
  - If not pending: a single ghost `Undo Status` button that flips to the opposite status

**Polling on this screen:** every **3000 ms** while processing; on reaching `completed` it fetches
violations, auto-selects the first one, and clears the interval.

**Note:** `Badge` is imported in `app/jobs/[id]/page.tsx` but never used there.

---

## 6. Screen: `/admin`

Container `max-w-4xl mx-auto py-12 px-6 space-y-12`.

- **Header**: `h1` "Admin Dashboard" + "System maintenance and data management." and an
  "Exit Admin" outline button routing to `/`.
- **Alert lines**: error (`bg-destructive/10 text-destructive`) and message
  (`bg-primary/10 text-primary`) blocks.
- **Three stat cards** in `md:grid-cols-3`, each a Card with a tiny uppercase muted title and a
  `text-2xl font-bold` value, showing `...` while loading:
  - "Jobs" → `total_jobs`
  - "Markers" → `total_violations`
  - "Storage" → `(uploads_mb + exports_mb).toFixed(1) + " MB"`
  Note `jobs_by_status`, `files_count`, and the uploads/exports split are returned by the API but
  **not displayed**.
- **"Danger Zone" card** (`border-destructive/20`), description "Destructive actions that wipe
  system data.", containing three bordered rows each with a title, description, and a destructive
  "Run" button:
  - "Reset Database" — "Clear all job records and markers."
  - "Clear Storage" — "Purge all media files from volume."
  - "System Wipe" — "Full factory reset of all data."
  Each is gated by a native `window.confirm("Reset {type}? Action is final.")`.

---

## 7. Client data model (`lib/api.ts`)

`API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"`.
Errors are thrown as `APIError { status, message }` built from the response body's `detail` field.

```ts
Job {
  id, filename, original_filename: string|null,
  media_type: "audio"|"video",
  prompt: string|null,
  status: "pending"|"converting"|"transcribing"|"analyzing"|"exporting"|"completed"|"failed",
  auto_fix, auto_scrub: boolean,
  preset: string|null,
  duration_seconds: number|null,
  language: string|null,
  created_at: string,
  error_message: string|null,
  violation_count, pending_count, accepted_count, rejected_count: number
}

Violation {
  id, job_id, text,
  start_time, end_time: number,
  label: string|null,
  rule_violated: string|null,
  severity: "high"|"medium"|"low"|null,
  reasoning: string|null,
  status: "pending"|"accepted"|"rejected",
  action: "cut"|"mute"
}

Preset { id, name, description }
ExportResponse { job_id, export_filename, message }
AdminStats { total_jobs, total_violations, jobs_by_status: Record<string,number>,
             total_uploads_size_mb, total_exports_size_mb, files_count }
```

`JobListItem` is the list-endpoint shape: like `Job` but without `language`, `error_message`, or the
three per-status counts (only `violation_count`).

**Upload multipart fields:** `file`, `prompt` (omitted when a preset is set), `auto_fix`,
`auto_scrub`, `preset` (omitted when null).

**Export call:** `POST .../export` with body `{ edit_action: null }` — the frontend always sends
`null`, meaning "honor each violation's own cut/mute". The API supports forcing `"cut"` or `"mute"`
globally, but **no UI exposes that**.

---

## 8. State that exists in the API but has no UI

- `DELETE /api/jobs/{id}` — `api.deleteJob()` is implemented in the client but called from nowhere;
  there is no delete control on any screen.
- `GET /api/jobs/{id}/audio/waveform` — `api.getWaveform()` is implemented but unused; the Waveform
  component decodes the media directly through wavesurfer instead of using the cached peaks.
- Global `edit_action` override on export (see above).
- Bulk-update with arbitrary label filters — the UI only ever sends the two scrubber labels.
- `Job.language`, `pending_count`, `accepted_count`, `rejected_count` — fetched, never rendered.
- `AdminStats.jobs_by_status` and `files_count` — fetched, never rendered.
- No search, filter, sort, or pagination exists on the job list or the violation list.
- No keyboard shortcuts are bound anywhere.
- No toast/notification system; errors are inline strings and one `window.confirm`.

---

## 9. Demo fixture (useful for mockups with realistic content)

`tests/fixtures/demo/` holds a synthetic 74-second two-speaker seminar (`demo_seminar.mp3` /
`.mp4`, generated with `gpt-4o-mini-tts`, voices "alloy" as HOST and "ballad" as GUEST) plus
`expected_violations.json` and `seed_job.json`.

Representative transcript lines (these are the strings that appear in violation cards):

- "So, um, welcome back, and, you know, let's just dive right into today's story." (0.0–5.0)
- "Uh, yeah, so in my fourth month I brought home eleven thousand four hundred dollars, and that
  changed everything." (5.0–13.55)
- "Honestly, by December I quit my job, right before Christmas, and it felt unreal." (19.4–25.85)
- "And, ah, three months later there was a shiny little sports car sitting in my driveway, paid for
  in cash." (25.85–34.4)
- "Yeah, hm, my mother's migraines just disappeared after she started on the wellness pack…"

The content mix is deliberate: income claims, lifestyle claims, health claims, and filler words —
i.e. both LLM-found violations and scrubber-found filler in one file.

---

## 10. Existing demo narrative (the story the UI is expected to tell)

`docs/demo/narration.md` and `docs/demo/slide-copy.md` define a 3-minute, 10-scene portfolio demo.
Scenes 1–3 and 9–10 are slides; **scenes 4–8 are screen capture of the actual UI**:

| Scene | Screen | What must be visible |
|---|---|---|
| 4 — Upload (18 s) | `/` | typing an instruction, selecting a preset then switching back, checking scrubber mode, dropping a file |
| 5 — Pipeline (12 s) | processing view | stepper moving through Transcribing → Analyzing → Exporting → Ready to review |
| 6 — Review (26 s, centrepiece) | `/jobs/[id]` | colored waveform markers, moving playhead, clicking a marker to open its card with quote + reasoning + timecode, Play Clip |
| 7 — Cut/mute/clean (18 s) | `/jobs/[id]` | toggling one edit from cut to mute, accepting it, then Clean All accepting all filler/dead-air and disappearing |
| 8 — Export (18 s) | `/jobs/[id]` | export runs, Download button appears, edited result plays back and is visibly shorter |

Slide taglines in use: "Copilot, not autopilot.", "Editing by ear doesn't scale",
"One instruction, one pass".

---

## 11. Backend API contract (authoritative)

FastAPI app titled `"CleanCut API"` v`1.0.0`. Routers: `jobs`, `violations`, `audio` all mount under
`/api/jobs`; `admin` under `/api/admin`. CORS origins from `CORS_ORIGINS` (default
`http://localhost:3000`), all methods and headers allowed. **No authentication on any endpoint,
including `/api/admin/*`.**

### Endpoint table

| Method | Path | Params | Success | Errors |
|---|---|---|---|---|
| GET | `/` | — | `{"status":"ok","message":"CleanCut API is running"}` | — |
| POST | `/api/jobs` | multipart: `file`, `prompt`, `media_type` (default `"audio"`), `auto_fix`, `auto_scrub`, `preset` | `JobResponse`, status `pending`, all counts 0 | 400, 413, 422, 500 (see below) |
| GET | `/api/jobs` | — | `JobListResponse[]`, `created_at` DESC | — |
| GET | `/api/jobs/presets` | — | `PresetResponse[]` | — |
| GET | `/api/jobs/{id}` | — | `JobResponse` | 404 `"Job not found"` |
| DELETE | `/api/jobs/{id}` | — | `{"message":"Job deleted"}` | 404 |
| GET | `/api/jobs/{id}/violations` | — | `ViolationResponse[]`, `start_time` ASC | 404 |
| PATCH | `/api/jobs/{id}/violations/{vid}` | body `{status?, action?}` | `ViolationResponse` | 404, 400 |
| POST | `/api/jobs/{id}/violations/bulk-update` | query `labels` (repeatable), body `{status?, action?}` | `{"message":"Updated N violations"}` | 404 |
| GET | `/api/jobs/{id}/audio` | — | `FileResponse` | 404 ×2 |
| GET | `/api/jobs/{id}/audio/waveform` | — | `{"peaks":[…800 floats…]}` | 404 ×2, 500 |
| POST | `/api/jobs/{id}/export` | body `{edit_action: "cut"\|"mute"\|null}` | `ExportResponse` | 404, 400, 500 |
| GET | `/api/jobs/{id}/export/download` | — | file, `attachment` | 404 ×2 |
| GET | `/api/jobs/{id}/export/stream` | — | file, `inline` | 404 ×2 |
| GET | `/api/admin/stats` | — | `AdminStats` | — |
| POST | `/api/admin/reset-database` | — | `{"message":"Database wiped successfully"}` | 500 |
| POST | `/api/admin/clear-storage` | — | `{"message":"Storage cleared successfully. Deleted N files."}` | 500 |
| POST | `/api/admin/reset-all` | — | `{message, database, storage}` | 500 |

### Upload error copy (verbatim — these strings surface in the UI's error line)

| Status | Trigger | `detail` |
|---|---|---|
| 400 | unknown preset | `Unknown preset '{p}'. Available: income-claims, pii-redaction` |
| 400 | bad extension | `Unsupported file type. Allowed: {…}` |
| 413 | over size cap | `Upload exceeds the {N} MB limit.` |
| 413 | over duration cap | `Media is {X.X} minutes long, over the {Y} minute limit.` |
| 422 | ffprobe can't read duration | `Could not determine the media duration. The file may be corrupt, truncated, or in a container without duration metadata. Re-encode it (for example to MP3 or MP4) and upload again.` |
| 500 | file save failure | `str(e)`; job row is kept and marked `failed` |

Note the 422 message is long — it is the single longest error string the upload screen can display.

### Export response message

`ExportResponse.message` is built as `"Exported with {n} cut and {m} muted edit(s)"` (either clause
omitted if zero). **The frontend discards this string entirely** — it only flips to the Download
button.

### Other export errors worth designing for

- 400 `"Job not completed"`
- 400 `"No accepted edits to remove. Accept some suggested edits first."` (the frontend pre-empts
  this by disabling the button, so it is currently unreachable through the UI)
- 404 `"Export not found. Generate export first with POST /export"`

### PATCH validation copy
- `"Status must be 'pending', 'accepted', or 'rejected'"`
- `"Action must be 'cut' or 'mute'"`

Bulk-update performs **no** value validation and only touches violations whose status is currently
`pending`.

---

## 12. Job lifecycle (exact)

```
pending
  → converting     (ONLY when the upload extension is .aif / .aiff)
  → transcribing
  → analyzing
  → exporting      (ONLY when auto_fix OR auto_scrub is set)
  → completed
```
`failed` can replace any state. (`"processing"` appears in a `models.py` docstring but is never
written.) The `ProcessingView` stepper mirrors this sequence exactly, including both conditional
stages.

**Important UI consequence:** violations are committed only at the `exporting`/`completed`
transition. Polling `GET /violations` during `analyzing` returns an **empty array**, not a partial
list. There is no incremental reveal to design around.

### Initial violation status
- Scrubber-origin (`"Dead Air"`, `"Filler Word"`): `accepted` if `auto_scrub`, else `pending`.
- Everything else: `accepted` if `auto_fix`, else `pending`.

So "Auto-apply markers" and "Scrubber mode" both mean *pre-accept*, and both cause an export to be
rendered before the user has seen anything.

---

## 13. Labels, severities, actions

**Scrubber labels (deterministic, exhaustive, always these two):** `"Dead Air"`, `"Filler Word"`.
These are the two the sidebar's `SCRUB_LABELS` / "Clean All" targets.

**Dead Air text values** (shown verbatim in the quote slot — they are bracketed markers, not
speech): `"[Total Silence]"`, `"[Initial Silence]"`, `"[Gap]"`, `"[Final Silence]"`. Threshold is a
gap strictly greater than **2.0 s**.

**Filler words detected:** `um, uh, ah, er, hm, like, you know`. (`"you know"` is a two-word phrase
matched against single tokens, so it never fires in practice.) Consecutive fillers less than 0.5 s
apart merge into one violation whose reasoning becomes `"Detected multiple consecutive filler
words."` — meaning a single card can hold several words.

**Preset-mode labels** (model-produced, *not* validated, so arbitrary strings are possible):
- `income-claims` → `Income Claims`, `Lifestyle Claims`, `Political/Religious`,
  `Medical/Health Claims`, `Business Opportunity Misrepresentation`, `Competitive Disparagement`;
  fallback `Income & Lifestyle Claims`.
- `pii-redaction` → `Direct Identifiers`, `Government/Financial Identifiers`,
  `Credentials & Access`, `Health & Protected Categories`, `Confidential Business Information`;
  fallback `PII Redaction`.

**Prompt-mode labels:** free-form; the system prompt suggests `Filler Word`, `Income Claim`,
`Off-topic`. Guaranteed fallback is `"Marker"`.

Design consequence: **label length is unbounded and can be long** (e.g. "Business Opportunity
Misrepresentation" is 40 chars) — it renders both as a truncated sidebar line and as a `text-xl
font-bold` card title.

**Severity** is `high`/`medium`/`low`/`null`, and is populated **only in preset mode**. Scrubber
violations always have `severity = null` and `rule_violated = null`. In prompt mode both are
normally null. So the severity badge and the "Rule Violated" block are *preset-mode-only* UI.

**Action** is `cut` or `mute`, defaulting to `cut`.

---

## 14. Presets

| | `income-claims` | `pii-redaction` |
|---|---|---|
| name | `Income & Lifestyle Claims` | `PII Redaction` |
| description | `FTC-style earnings and lifestyle claim review for direct-selling material.` | `Flags spoken personal, financial, and credential data for muting.` |
| default_action | `cut` | `mute` |
| rulebook | `presets/income-claims.md` (6 prohibited categories + context-sensitive word list: *partnership, retired, freedom, investment* + a rule that both original and translated speech be flagged) | `presets/pii-redaction.md` (5 categories; instructs "prefer mute over cut" and to flag the minimum span) |

Presets are registered in a dict in `prompt_analyzer.py`; insertion order is the order the select
box shows. Adding one is a markdown file + a dict entry, so **the preset list should be treated as
growing** — the current `<select>` holds two.

**Prompt mode cut/mute default is keyword-derived:** the action defaults to `mute` if the prompt
contains any of *redact, mute, silence, bleep, censor, anonymize, obscure, pii, personally
identifiable* and none of *cut, remove, delete, trim, strip, take out, excise, drop*; otherwise
`cut`. This inference is invisible in the current UI.

---

## 15. Limits & environment

- **Upload size:** `MAX_UPLOAD_MB`, default **500** (decimal MB = 500,000,000 bytes). Enforced on
  bytes actually written, not on `Content-Length`.
- **Duration:** `MAX_DURATION_MINUTES`, default **120 minutes**, probed with ffprobe (30 s timeout).
  Unknown duration fails closed with 422.
- **Accepted extensions (server):** `.mp3 .wav .m4a .flac .ogg .webm .aif .aiff .mp4 .mov` —
  identical to the frontend's regex. **Extension only; no MIME sniffing.**
- `.aif`/`.aiff` are missing from the serving MIME map, so they stream as
  `application/octet-stream`.
- **Boot requirements:** non-empty `OPENAI_API_KEY`, `ffmpeg` and `ffprobe` on PATH, unless
  `SKIP_PREFLIGHT=1`.

---

## 16. Timing / async facts that constrain UI

- **One worker thread, strictly sequential.** A second upload waits behind the first. **No endpoint
  exposes queue depth or position** — queue size is only logged to stdout. The processing view's
  "Queued" state cannot currently say *how* queued.
- **No websocket, no SSE, no progress percentage, no ETA anywhere in the API.** Polling `GET
  /api/jobs/{id}` for a changing `status` string is the only mechanism. Both screens poll at 3 s.
- **No sub-stage progress.** Inside `transcribing` and `analyzing` nothing is emitted; chunk
  progress goes to stdout only. This is why the stepper uses an indeterminate sweeping bar.
- **Transcription:** local `faster-whisper`, model size `medium`, CPU, `int8`, `word_timestamps`,
  `vad_filter`. Lazy-loaded and module-cached — **the first job after a server start additionally
  pays model-load time.** Cost scales with media length.
- **Analysis:** OpenAI `gpt-4o`, `temperature=0.1`, JSON response format. One call if ≤100 segments;
  otherwise chunks of 50 segments with 10 overlap (step 40) → roughly `ceil((n−10)/40)` sequential
  API calls. ~50 segments ≈ 2–3 minutes of audio.
- **Export is synchronous** — `POST /export` blocks on ffmpeg for the whole re-encode with no status
  change and no progress signal. The current UI shows only an "Exporting..." button label for that
  entire window.
- **Waveform is cached** in `jobs.waveform_data`, exactly **800 peaks**, floats 0.0–1.0 to 3 dp.
  First request triggers a full ffmpeg decode (slow on long files); later requests are a DB read.
  The cache is never invalidated and always reflects the **original** upload, never the export.
  The frontend does not use this endpoint at all — wavesurfer decodes the media client-side.
- **Auto-fix / auto-scrub jobs already have an export on disk** before the user opens the review
  screen, so `GET /export/download` can succeed on a job the user never exported. The current UI
  does not detect or surface this.

### `error_message` is overloaded — two different meanings

| Job status | `error_message` meaning |
|---|---|
| `failed` | the failure reason |
| `completed` | **a warning**: `Partial analysis: N section(s) of the transcript could not be analyzed and may contain unflagged content. ` + up to 3 chunk messages joined by ` \| `, each `chunk {i}/{n} [{start}s-{end}s]: {error}` |

Both surfaces already exist in the UI (the `<pre>` on the failed screen, the amber banner on the
review screen). The partial-analysis string can be long and contains pipe-delimited technical
detail.
