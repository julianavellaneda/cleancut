"""
Transcription and analysis: turning a recording into suggested edits.

- ``transcriber``     - faster-whisper, word-level timestamps.
- ``prompt_analyzer`` - the chunked LLM pass and the preset registry.
- ``providers``       - the model router behind ``CLEANCUT_MODEL``.
- ``analyze``         - the standalone CLI (``python -m app.analysis.analyze``).

This file exists to make the directory a regular package, which its three
siblings - ``routes``, ``services`` and ``eval`` - already were. Without it the
directory is an implicit namespace package nested inside a regular one, so the
same file is reachable both as ``analyze`` and as ``app.analysis.analyze``. A
module importable under two names is two distinct classes; that is exactly the
failure ``tests/test_cli_entrypoint.py`` pins for ``Violation``, and it is why
this is a correctness fix rather than a formality.

Deliberately no re-exports. ``eval/__init__.py`` has them because that package
is consumed as a unit; here every caller imports the specific module it wants,
and adding a second import path for the same names is the thing above.
"""
