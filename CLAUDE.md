# CLAUDE.md

@AGENTS.md

<!--
The line above is a Claude Code import, not a link: it splices AGENTS.md into context at load time.

AGENTS.md is the single source of truth for this repository's architecture, in the open format
(https://agents.md) that Codex, Cursor, Copilot, Gemini CLI, Aider, Zed and others read natively.
Claude Code does not read AGENTS.md itself yet - https://github.com/anthropics/claude-code/issues/6235 -
so this file exists purely to bridge that gap.

Keep it that way. Anything written directly below the import is, by construction, a fact that only
Claude Code sees, and this repository has already been burned once by an architecture note living in
a file the other tools did not read: the deleted GEMINI.md drifted far enough to state the opposite
of the truth about admin auth. Architecture goes in AGENTS.md. This file takes Claude-Code-specific
operational settings and nothing else.
-->
