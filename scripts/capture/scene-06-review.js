// Scene 6 - the money shot. Seed first:
//   python scripts/seed_demo_job.py --state fresh
//   playwright-cli run-code --filename=scripts/capture/scene-06-review.js
//
// Beats: playhead crosses the waveform, then a marker opens and the LLM's
// quoted text is shown sitting on the exact words it came from.

async page => {
  const JOB = 'demo-0000-0000-0000-cleancut';
  // The label of the marker to open. Verify against the seeded data before a
  // take - prompt mode lets the model choose its own labels.
  const MARKER = 'Income Claim';

  const ring = async (locator, pad = 8) => {
    const b = await locator.boundingBox();
    if (!b) return { dispose: async () => {} };
    return page.screencast.showOverlay(`
      <div style="position:absolute;
        top:${b.y - pad}px; left:${b.x - pad}px;
        width:${b.width + pad * 2}px; height:${b.height + pad * 2}px;
        border:2px solid rgba(56,189,248,.95); border-radius:12px;
        box-shadow:0 0 0 7px rgba(56,189,248,.16), 0 0 18px rgba(56,189,248,.35);
        pointer-events:none;"></div>
    `);
  };

  page.context().on('page', p => p.close().catch(() => {}));

  await page.goto(`http://localhost:3000/jobs/${JOB}`);
  // The transport stays disabled until wavesurfer fires 'ready'.
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Play');
    return !!b && !b.disabled;
  }, null, { timeout: 120000 });
  await page.waitForTimeout(2000);

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-06-review.webm',
    size: { width: 1440, height: 900 },
  });
  await page.waitForTimeout(1600);

  const play = page.getByRole('button', { name: 'Play', exact: true });
  let r = await ring(play, 6);
  await page.waitForTimeout(700);
  await play.click();
  await r.dispose();
  await page.waitForTimeout(7000);                       // playhead crosses the waveform
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await page.waitForTimeout(1200);

  const marker = page.locator('aside').getByText(MARKER, { exact: true }).first();
  r = await ring(marker, 10);
  await page.waitForTimeout(800);
  await marker.click();
  await page.waitForTimeout(500);
  await r.dispose();
  await page.waitForTimeout(2600);                       // dwell on the quote and the timecode

  const clip = page.getByRole('button', { name: /Play Clip/ });
  r = await ring(clip, 6);
  await page.waitForTimeout(700);
  await clip.click();
  await r.dispose();
  await page.waitForTimeout(6000);                       // clip plays and auto-pauses

  await page.screencast.stop();
}
