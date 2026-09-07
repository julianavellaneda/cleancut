**What this changes, and why**

<!-- The reasoning, not the diff - the diff is right there. If it fixes something, say what went
     wrong rather than what you renamed. -->

**Checks**

Backend, from `backend/` (see [`CONTRIBUTING.md`](../CONTRIBUTING.md#running-what-ci-runs) for the
exact commands and the eval thresholds):

```bash
# If requirements*.in changed, re-compile both locks first (see CONTRIBUTING.md) and
# confirm no diff:
git diff --exit-code -- requirements.txt requirements-dev.txt

ruff format --check app tests conftest.py
ruff check app tests conftest.py
mypy
pytest --cov=app --cov-config=pyproject.toml --cov-report=term-missing
python -m app.eval.run ../tests/fixtures/demo/seed_job.json
python -m app.eval.run --detectors ../tests/fixtures/demo/demo_seminar.mp3 --suite scrub \
  --min-precision 0.95 --min-recall 0.85
```

Frontend, from `frontend/`:

```bash
npm run lint && npx tsc --noEmit && npm test && npm run build
```

- [ ] Backend checks above pass, including both evals clearing their floors
      <!-- If the eval numbers moved, quote the before and after here and say why. -->
- [ ] Frontend checks above pass
- [ ] A new suppression (`# noqa`, `# type: ignore`, eslint-disable) carries a comment saying why
- [ ] Any new fixture is synthetic — no real recording, transcript, or personal data
- [ ] A new database column has a case in `backend/tests/test_migrations.py`

**Docs**

- [ ] `AGENTS.md` updated if the architecture moved. It is the single source of truth and the file
      every agent tool reads; `CLAUDE.md` is a one-line import of it, so there is nothing to mirror.
- [ ] README updated if a command, an endpoint, or an environment variable changed
