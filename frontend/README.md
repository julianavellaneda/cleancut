# CleanCut — frontend

The Next.js 16 review interface. Source is under `src/`: `src/app/jobs/[id]/page.tsx` is the review
screen, `src/components/Waveform.tsx` draws the markers, and `src/lib/api.ts` is the only place the
backend is called from.

```bash
npm install && npm run dev    # needs the backend on :8000 — see ../README.md
```

The browser calls a relative `/api`, which `src/app/api/[...path]/route.ts` proxies to
`BACKEND_ORIGIN` at request time. That indirection is deliberate and load-bearing; it is explained
in [`../CLAUDE.md`](../CLAUDE.md).

Colour, type, motion and focus all come from the design system — four rules, each of which has
already been broken once, plus a contrast audit (`src/app/contrast.test.ts`) that fails the build if
a token pairing drops below its threshold. Read
[the design system notes](../CLAUDE.md#design-system) before styling anything.

```bash
npm run lint && npx tsc --noEmit && npm test && npm run build   # what CI runs
```
