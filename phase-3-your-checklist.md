# Phase 3 — What You Need To Do

Plain-English companion to `phase-3-portfolio-plan.md`. That file is my work. This one is yours.

Total time on your side: **about 90 minutes**, plus a few dollars.

---

## The short version

1. Make sure your OpenAI key has a couple of dollars on it.
2. Pick and install a screen recorder (one download).
3. Record a 3-minute screen capture with your voice, reading a script I'll hand you.
4. Create one empty GitHub repo.
5. Paste the finished case study onto julianavellaneda.dev.

That's the whole list. Details below.

---

## 1. Claude Code skills — you need to install nothing

I looked into this first, since you asked. Most of the third-party demo-video and GIF skills
(`claude-gif`, `vorec`, the wilwaldon Video Toolkit, a video-to-GIF skill) are wrappers around
`ffmpeg` — which this project already requires and which I can call directly. Installing them means
running an install script piped from someone else's GitHub repo for capability I already have.
**Skip those.**

The skills I *will* use are already on your machine: `playwright-cli` (to script a clean, repeatable
browser recording), `plain-english` (so the README and case study don't read as AI-written), and
`code-review`.

### The one you asked about — digitalsamba's video toolkit

You sent me `digitalsamba/claude-code-video-toolkit#templates`, and it's a better find than the
others. Different category:

- MIT license, no required API keys, and it's a **separate workspace**, not something you install
  into CleanCut. You clone it somewhere else, run `claude` inside that folder, make the video there,
  and copy the finished MP4 out. Nothing touches your project.
- Its **`product-demo`** template is a real Remotion (React) video project with proper scenes —
  title, problem, solution, demo, stats, call-to-action — plus animated backgrounds, browser and
  terminal chrome, and animated stats cards. That's genuine polish I can't produce with ffmpeg alone.

**My recommendation: use it for the bookends only, and only after the real recording exists.**

The heart of the video has to stay a real screen capture of your app working, with your voice over
it. That's what convinces someone you built the thing. What this template can add is the opening
title card and the closing architecture/repo card — the parts that currently look homemade.

Two warnings:

1. Its default look is "dark tech SaaS launch ad." On an engineering portfolio piece that can
   backfire — it makes a real system look like marketing for a product that doesn't exist. We'd use
   its structure and override the styling.
2. It wants stats cards. **We only fill one in if the eval fixture gives a real accuracy number.**
   A made-up metric on screen is the fastest way to lose an interview.

**Your action:** nothing yet, and nothing required. If you want the polished bookends, say so and
I'll timebox it to about two hours *after* the screen capture is done. It blocks nothing, and if the
result looks worse than a plain title card we bin it and lose nothing. Requires Node 18+ on your
machine, which you already have from the frontend.

---

## 2. OpenAI credit — a few dollars

The demo clip is generated with OpenAI's text-to-speech, using the same `OPENAI_API_KEY` already in
your root `.env`.

A 4-minute script costs roughly **$0.05–0.10**. Even with re-generations while we tune the voices,
call it under a dollar. ([pricing reference](https://tokenmix.ai/blog/gpt-4o-mini-tts-cheapest-tts-api-2026))

**Your action:** confirm the key on that account has credit. If the account is empty, add $5. If
you'd rather not spend anything, say so — macOS has a free built-in `say` command I can use instead,
but it sounds robotic and will make the demo video worse.

---

## 3. Screen recorder — pick one, install it

You need something that records your screen *and* your microphone at the same time, at retina
resolution. My recommendation, cheapest first:

| Tool | Cost | Why |
|---|---|---|
| **QuickTime** (already installed) | Free | Good enough. No auto-zoom, no polish, but it works and it's on your Mac now. Start here. |
| **ScreenKite** | Free | Native Mac, built for product demos, has the auto-zoom that makes small UI text readable. Free tier covers a 3-min video. |
| **CursorClip** | $59 one-time | The Screen Studio alternative without a subscription. Auto-zoom, motion blur, the polished look. |
| **Screen Studio** | Subscription | The industry default. Best output. Only worth it if you'll make more of these. |

Honest read: **try QuickTime first.** If the recording looks flat and the UI text is hard to read,
then grab ScreenKite (free) before spending money. The auto-zoom is the only feature that
meaningfully improves a demo like this.

([alternatives comparison](https://cursorclip.com/blog/screen-studio-alternatives/) ·
[Mac screen recorders](https://screencharm.com/blog/best-screen-recording-software-mac))

**Your action:** install one. Do a 10-second test recording with your voice and confirm the audio
isn't clipping.

---

## 4. Record the demo — about 45 minutes

I'll give you three files before this step:

- `docs/demo/shot-list.md` — what to click, in order, with timings
- `docs/demo/narration.md` — the exact words to say, timed to the clicks
- `docs/demo/recording-setup.md` — window size, what to hide, pre-flight checklist

You read the script over the screen capture. Two or three takes is normal; you don't need a perfect
one, because I'll trim and clean the audio afterward.

Quick tips:
- Set your browser window to **1440×900**. Bigger looks impressive live and unreadable after
  compression.
- Close Slack, Messages, and anything that shows a notification.
- Any headset mic beats your laptop mic. Record somewhere without echo.
- Don't stop for a stumble. Pause for two seconds, say the line again, keep going. I'll cut it.

**Your action:** record it, then tell me where the file is. I'll trim, normalize the audio, add
captions, and encode it for the web.

---

## 5. Create the public GitHub repo — 5 minutes

We agreed on a **fresh repo with a single squashed commit** and no history — because the current
history still contains the real client transcripts, the violations JSON, and the client rules file.
Publishing this repo as-is would publish all of that. A fresh repo makes it impossible to miss one.

**Your action:**
1. Create a new **public, empty** repo on GitHub. Suggested name: `cleancut`. **Do not** add a
   README, `.gitignore`, or license — leave it completely empty.
2. Give me the URL.

I'll build the clean tree, verify every single file that's in it, and hand it back for you to push.
This repo stays private as your archive of the real client work — nothing gets deleted.

---

## 6. Host the demo video — 10 minutes

Once I hand back the encoded MP4, it needs to live somewhere linkable:

- **YouTube (unlisted)** — recommended. Free, reliable, embeds anywhere, no bandwidth cost, and the
  link never rots.
- **Directly on julianavellaneda.dev** — nicer if your host handles video well; more bandwidth and
  more to maintain.
- **Loom** — fastest, but the free tier's branding cheapens a portfolio page.

**Your action:** upload it (unlisted YouTube is fine) and send me the link so I can put it in the
README and the case study.

---

## 7. Publish the case study — 15 minutes

I'll write `docs/CASE_STUDY.md` — roughly 1,000 words, leading with the genuinely hard engineering
(timestamp alignment, A/V-sync-preserving edits, chunked analysis of long transcripts) rather than
"I built an AI app."

**Your action:** paste it into your site and publish. If you'd rather I write it directly into the
portfolio site's repo in its own content format, point me at that repo and I'll do that instead —
just say the word.

---

## Questions still open (answer whenever)

1. **Repo name** — is `cleancut` taken on your GitHub? Any name preference?
2. **Your voice in the demo clip audio?** The plan is TTS voices for the fake seminar, and your
   voice only for the narration over the screen capture. Confirm you're fine being audible in the
   narration at all — if not, I'll write on-screen captions instead and the video runs silent.
3. **Spanish in the demo clip?** I want one Spanish sentence mid-paragraph, because code-switching
   is a real strength of the engine and worth showing. It also makes the clip visibly unrelated to
   any single market. Any objection?
4. **Do you want the eval numbers public?** The demo clip comes with ground-truth timestamps, so I
   can measure how accurately the LLM catches the planted items. If the number is good it belongs in
   the case study. If it's mediocre, we leave it out. Fine to decide after we see it.

---

## What I need from you to start

Only item 2 (confirm OpenAI credit) blocks me. Everything through Step 2 of the dev plan — the
rehearsal, the demo script, the audio generation, the eval fixture — I can do without you. Give me
the go-ahead and I'll start with the end-to-end rehearsal.
