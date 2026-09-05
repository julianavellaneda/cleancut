**What this changes, and why**

<!-- The reasoning, not the diff - the diff is right there. If it fixes something, say what went
     wrong rather than what you renamed. -->

**Checks**

- [ ] `pytest` passes (`cd backend && pytest`)
- [ ] `npx tsc --noEmit && npm test && npm run build` passes in `frontend/`
- [ ] `npx eslint .` is clean, or a new suppression carries a comment saying why
- [ ] Both evals still clear their floors:
      `python -m app.eval.run ../tests/fixtures/demo/seed_job.json` and
      `python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub
      --min-precision 0.95 --min-recall 0.85`
      <!-- If the numbers moved, quote the before and after here and say why. -->
- [ ] Any new fixture is synthetic — no real recording, transcript, or personal data
- [ ] A new database column has a case in `backend/tests/test_migrations.py`

**Docs**

- [ ] `AGENTS.md` updated if the architecture moved. It is the single source of truth and the file
      every agent tool reads; `CLAUDE.md` is a one-line import of it, so there is nothing to mirror.
- [ ] README updated if a command, an endpoint, or an environment variable changed
