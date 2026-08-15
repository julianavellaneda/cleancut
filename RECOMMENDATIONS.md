# Recommendations & Roadmap — ai-audio-editing

*General direction doc (Aug 2026). Specifics can be finalized as work happens in-project.*

## Why this project matters

This is the strongest hidden portfolio piece in the entire projects folder: a complete, real-client AI product — Whisper transcription → LLM analysis (prompt-driven, not hardcoded) → waveform/video review UI → surgical FFmpeg cut/mute editing. It is exactly the shape 2026 hiring managers screen for (shipped, deployed, production-concerned AI systems), but right now it's invisible: client-branded, unpublished, no demo, no case study.

**Goal: turn it from "client work on my disk" into a public, linkable, generic AI product.**

---

## 1. Rebrand & genericize (highest priority)

The client-specific framing limits it. The engine is already generic (Phase 1 made analysis prompt-driven), so the rebrand is mostly naming and copy.

- [ ] Pick a neutral product name (ideas: **ClipComply**, **RedactAI**, **CleanCut AI**, **MarkCut**). Rename repo accordingly (keep `ai-audio-editing` remote as-is or rename on GitHub — GitHub redirects old URLs).
- [ ] Scrub client-specific references from README, UI copy, prompts, and docs. Reposition as: *"AI-powered media review & editing — describe what to find in plain English, review flagged moments on a waveform, and export a surgically edited file."*
- [ ] Frame compliance as the flagship *use case* (income claims, regulated speech), not the identity. Other use cases to mention: podcast cleanup, interview redaction (PII), filler-word scrubbing.
- [ ] Confirm nothing client-confidential is in git history (uploaded media, client guideline docs, names). If any, rewrite history or start a fresh public repo from a clean squash.

## 2. Portfolio packaging

- [ ] **Demo video (2–3 min):** upload a sample clip → prompt "flag any income claims" → review markers on the waveform → mute one, cut one, Clean All fillers → export. This single video is the highest-leverage artifact.
- [ ] **Sample media:** record or generate 1–2 royalty-free demo clips (a fake "seminar" audio with planted violations works great and shows the LLM catching them).
- [ ] **README overhaul:** hero screenshot/GIF at top, one-paragraph pitch, architecture diagram (upload → job queue → Whisper → LLM → review → FFmpeg export), quickstart via `./start.sh` or `docker compose up`.
- [ ] **Case study page** on julianavellaneda.dev: the problem (manual compliance review of hours of recordings), the solution, hard technical bits worth bragging about — word-level timestamp alignment, A/V-sync-preserving trim/concat filter chains, crossfades, multi-language/code-switching, job queue for long-running media processing.
- [ ] Add to resume/cv.md as a top-3 project bullet (real client work + AI product = strongest combination you have).

## 3. Light hardening (make the demo trustworthy)

Not a full production pass — just enough that a hiring manager poking at it doesn't hit sharp edges.

- [ ] Verify a fresh-clone setup actually works end-to-end (README steps reference a `poc/` dir for `.env` that doesn't exist in this repo — fix instructions).
- [ ] Make the LLM provider pluggable or at least document the OpenAI key requirement clearly; consider adding Anthropic as an option (nice resume echo with JobVault's multi-provider design).
- [ ] Error states: bad file, no API key, LLM timeout — fail visibly, not silently.
- [ ] Add a handful of tests around the highest-risk logic (timestamp math, FFmpeg filter construction) if thin — interviewers ask "how do you know the cut is frame-accurate?"
- [ ] Basic evals: a small fixture set of clips with known violations and an assertion that flags land within N ms. Even 5 cases is a differentiator ("I eval my LLM features").

## 4. Deploy a live demo (stretch, big payoff)

A URL beats a repo. Options, cheapest-first:

- **Demo mode:** pre-processed sample jobs baked in, so visitors can explore the review UI with zero API cost (no uploads). Deployable free on any static/small host + Fly.io/Railway for the API.
- **BYO-key mode:** allow uploads only with a user-supplied OpenAI key (same pattern as JobVault — consistent personal brand: "your data, your keys").
- Guardrails if uploads are open: file size/duration caps, rate limiting, auto-delete media after N hours (`data_retention: false` is already the stance — advertise it).

## 5. Business track (later, optional — after employment)

Market check (mid-2026): enterprise call-compliance incumbents (NICE, Verint, Level AI) run ~$110+/agent/mo and ignore the MLM / financial-coaching / insurance-content mid-market — a real gap. But selling to compliance buyers solo requires trust signals (SOC2, references) and long sales cycles. Score: ~2/5 as a first business; excellent as a portfolio piece regardless.

If pursued later:
- Start with one niche (e.g., financial-advice content creators who fear FTC/SEC exposure) and a self-serve tier, not enterprise sales.
- Position as *assistive review* ("flags for a human reviewer"), never *automated compliance* — keeps liability sane; keep a human-in-the-loop accept/reject step always.
- Pricing anchor: per-hour-of-media processed (usage-based) rather than per-seat.

---

## Suggested timeline (general)

| When | What |
|---|---|
| **Days 1–2** | Rebrand + scrub (name, copy, history check). Fix fresh-clone setup. |
| **Days 3–4** | Sample media + demo video + README overhaul with screenshots. |
| **Day 5** | Case study on portfolio site; resume/cv.md updated; repo public. |
| **Week 2 (optional)** | Demo-mode deploy at a real URL; tiny eval fixture set; error-state pass. |
| **Post-offer** | Decide on the SaaS track. |

**Definition of done (portfolio scope):** public repo with polished README, a 2–3 min demo video, a case-study link on julianavellaneda.dev, and the project listed on the resume. Everything past that is bonus.
