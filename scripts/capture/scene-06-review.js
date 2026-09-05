// Scene 6 - the money shot. Seed first:
//   python scripts/seed_demo_job.py --state fresh
//   playwright-cli run-code --filename=scripts/capture/scene-06-review.js
//
// Beats: playhead crosses the waveform, a marker opens and the LLM's quoted
// text is shown sitting on the exact words it came from, the clip replays, and
// the edit is accepted.
//
// Selectors follow the organic design system: the suggestion list is a
// `listbox` of `option`s (it was a plain `aside` of divs before), and the
// detail actions carry their keyboard hint in the accessible name - "Play
// clip P", "Accept A". Match them loosely so a hint change does not break a
// take.

async page => {
  const JOB = 'demo-0000-0000-0000-cleancut';
  // The marker to open. Verify against the seeded data before a take - prompt
  // mode lets the model choose its own labels.
  const MARKER = /Income Claim/;

  const ring = async (locator, pad = 8) => {
    const b = await locator.boundingBox();
    if (!b) return { dispose: async () => {} };
    return page.screencast.showOverlay(`
      <div style="position:absolute;
        top:${b.y - pad}px; left:${b.x - pad}px;
        width:${b.width + pad * 2}px; height:${b.height + pad * 2}px;
        border:2px solid rgba(56,189,248,.95); border-radius:14px;
        box-shadow:0 0 0 7px rgba(56,189,248,.16), 0 0 18px rgba(56,189,248,.35);
        pointer-events:none;"></div>
    `);
  };

  page.context().on('page', p => p.close().catch(() => {}));

  await page.goto(`http://localhost:3000/jobs/${JOB}`);
  // The transport stays disabled until wavesurfer fires 'ready'. The button is
  // icon-only in the organic design, so its name is an aria-label and its
  // textContent is empty - matching on text waits forever.
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll('button')]
      .find(x => (x.getAttribute('aria-label') || '').trim() === 'Play');
    return !!b && !b.disabled;
  }, null, { timeout: 120000 });
  await page.waitForTimeout(2000);

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-06-review.webm',
    size: { width: 1440, height: 900 },
  });
  await page.waitForTimeout(1400);

  const play = page.getByRole('button', { name: 'Play', exact: true });
  let r = await ring(play, 6);
  await page.waitForTimeout(600);
  await play.click();
  await r.dispose();
  await page.waitForTimeout(5200);                       // playhead crosses the waveform
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await page.waitForTimeout(900);

  // An LLM suggestion, not a scrubber one: the quote is the whole point of the
  // shot, and the filler rows are one word long.
  const marker = page.getByRole('option', { name: MARKER }).first();
  await marker.scrollIntoViewIfNeeded();
  r = await ring(marker, 6);
  await page.waitForTimeout(700);
  await marker.click();
  await page.waitForTimeout(400);
  await r.dispose();
  await page.waitForTimeout(2400);                       // dwell on the quote and the timecode

  const clip = page.getByRole('button', { name: /Play clip/ });
  r = await ring(clip, 6);
  await page.waitForTimeout(600);
  await clip.click();
  await r.dispose();
  await page.waitForTimeout(4200);                       // clip plays and auto-pauses

  // Nothing is removed without a human accepting it - so show the accept.
  const accept = page.getByRole('button', { name: /Accept/ });
  r = await ring(accept, 6);
  await page.waitForTimeout(600);
  await accept.click();
  await r.dispose();
  await page.waitForTimeout(2200);                       // counts move, selection advances

  await page.screencast.stop();
}
