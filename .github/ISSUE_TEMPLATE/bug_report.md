---
name: Bug report
about: Something CleanCut did that it should not have
title: ''
labels: bug
assignees: ''
---

**What happened**

<!-- And what you expected instead. -->

**Steps to reproduce**

1.
2.
3.

**Where it broke**

<!-- If a job failed, which stage was it on when it did? The status is on the job card:
     converting / transcribing / analyzing / exporting. If an export produced the wrong
     audio, say which edits were accepted and whether they were cuts or mutes. -->

**Setup**

- How you ran it: <!-- docker compose / local quickstart / start.sh / published GHCR image -->
- `CLEANCUT_MODEL`: <!-- e.g. openai:gpt-4o, anthropic:claude-opus-5, or blank for the default -->
- OS and version:
- Media: <!-- audio or video, container/codec, roughly how long -->

**Logs**

<!-- The backend's output around the failure, and the browser console if the problem is in the
     review UI. Please redact API keys - they appear in .env, not usually in logs, but check. -->

**Anything else**

<!-- Do not attach a real recording. If a specific file is needed to reproduce this, describe what
     is in it, or produce a synthetic clip that fails the same way. -->
