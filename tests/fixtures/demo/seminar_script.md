# Seminar Demo Script

## About

This is a fully synthetic script for a fake "business opportunity seminar," written to be fed
to a text-to-speech model and turned into a short demo clip for a portfolio video of an
audio-editing tool. Every name, figure, product, and contact detail below is invented; it does
not depict any real person, company, product, brand, or market. The two-voice dialogue is
deliberately loose and unpolished, with filler words, a code-switch, and several planted
compliance issues worked in so the resulting audio exercises every detector the tool is meant
to catch. Total spoken word count: 175.

## Script

```
HOST | warm, upbeat, slightly rushed | So, um, welcome back, and, you know, let's just dive right into today's story.
GUEST | earnest, a little nervous | Uh, yeah, so in my fourth month I brought home eleven thousand four hundred dollars, and that changed everything.
[PAUSE 2.7]
HOST | curious, encouraging | That's amazing. What changed for you after that?
GUEST | proud, a bit rushed | Honestly, by December I quit my job, right before Christmas, and it felt unreal.
GUEST | grinning, casual | And, ah, three months later there was a shiny little sports car sitting in my driveway, paid for in cash.
[PAUSE 2.8]
HOST | soft, sincere | Er, and it wasn't just financial, right? There was something with your mom too.
GUEST | warm, heartfelt | Yeah, hm, my mother's migraines just disappeared after she started on the wellness pack, it genuinely cleared them up.
GUEST | affectionate, switching easily into Spanish | Mi mamá está muy feliz ahora.
HOST | measured, honest | Now, to be fair, some people try this and earn nothing at all, and that's just the truth.
[PAUSE 2.9]
HOST | practical, wrapping up | If you want, uh, more details, you know, just call us at five five five, oh one three three.
GUEST | friendly, closing | Or, um, email us, like, at grow dot spark at lumenrise dash living dot com.
HOST | warm, closing | Thanks for listening. See you at the next event.
```

## Planted items

| Line (first ~5 words) | Category | Expected to be flagged? |
|---|---|---|
| "so in my fourth month" | Income claim (specific dollar figure) | Yes |
| "by December I quit my" | Early-retirement / quit-your-job claim | Yes |
| "three months later there was" | Luxury-item / lifestyle result claim | Yes |
| "my mother's migraines just disappeared" | Health claim (product treated a condition) | Yes |
| "Mi mamá está muy feliz" | Non-English (Spanish) code-switch mid-turn | Yes |
| "call us at five five" | Fake phone number (555-0133) | Yes |
| "email us, like, at grow" | Fake email address (invented domain) | Yes |
| "some people try this and" | Honest disclaimer near the income claims | No (near-miss control) |
| "um" (x2), "uh" (x2), "ah", "er", "hm", "like", "you know" (x2) | Filler words | Yes |
