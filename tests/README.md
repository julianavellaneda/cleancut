# tests/

Media fixtures and eval labels shared across the project, plus this signpost.

`fixtures/demo/` holds the synthetic demo clip and its ground truth. Everything committed here must
be synthetic — see [`fixtures/demo/README.md`](fixtures/demo/README.md) for the full rule and the
provenance of each file.

Backend unit tests live in `backend/tests/` and run with `pytest` from `backend/`.
