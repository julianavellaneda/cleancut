# CleanCut — frontend

The Next.js 16 review interface. Source is under `src/`: `src/app/jobs/[id]/page.tsx` is the review
screen, `src/components/Waveform.tsx` draws the markers, and `src/lib/api.ts` is the only place the
backend is called from.

```bash
npm install && npm run dev    # needs the backend on :8000 — see ../README.md
```

The browser calls a relative `/api`, which `src/app/api/[...path]/route.ts` proxies to
`BACKEND_ORIGIN` at request time. That indirection is deliberate and load-bearing; it is explained
in [`../AGENTS.md`](../AGENTS.md).

Colour, type, motion and focus all come from the design system, not component defaults. Four rules,
each already broken once before it was written down:

- Colour lives only in `globals.css`; a component never carries a literal hex or `rgba()`.
- `--muted` is a text colour; `--faint` is not.
- Never dim live text with `opacity` — it can push a pairing below its contrast threshold.
- The focus ring is global (`:focus-visible`) and must not be suppressed with `outline-none`.

A contrast audit (`src/app/contrast.test.ts`) fails the build if a token pairing drops below its
threshold. Read [the design system notes](../AGENTS.md#design-system) for the reasoning behind each
rule before styling anything.

```bash
npm run lint && npx tsc --noEmit && npm test && npm run build   # what CI runs
```
