// Scene 7 - per-edit cut vs mute, then Clean All. Seed first:
//   python scripts/seed_demo_job.py --state fresh
//   playwright-cli run-code --filename=scripts/capture/scene-07-cut-mute-cleanall.js

async page => {
  const JOB = 'demo-0000-0000-0000-cleancut';
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
  await page.getByText(/^Suggested Edits \(\d+\)$/).waitFor();
  await page.waitForTimeout(2500);

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-07-cut-mute-cleanall.webm',
    size: { width: 1440, height: 900 },
  });
  await page.waitForTimeout(1400);

  await page.locator('aside').getByText(MARKER, { exact: true }).first().click();
  await page.waitForTimeout(1600);

  // Cut vs mute, per edit. Scope to <main>: 'cut'/'mute' also appear as badges
  // in the card header and in every sidebar row.
  const mute = page.locator('main').getByRole('button', { name: 'mute', exact: true }).last();
  let r = await ring(mute, 8);
  await page.waitForTimeout(900);
  await mute.click();
  await page.waitForTimeout(1800);                       // badge and region colour follow
  await r.dispose();

  const accept = page.getByRole('button', { name: 'Accept', exact: true });
  r = await ring(accept, 6);
  await page.waitForTimeout(700);
  await accept.click();
  await page.waitForTimeout(1600);
  await r.dispose();

  // Clean All takes every pending filler word and dead-air gap in one click,
  // deterministically, with no LLM involved. The button removes itself when the
  // pending scrub count hits zero.
  const cleanAll = page.getByRole('button', { name: /^Clean All \(\d+\)$/ });
  r = await ring(cleanAll, 8);
  await page.waitForTimeout(1100);
  await cleanAll.click();
  await page.waitForTimeout(2600);
  await r.dispose();
  await page.waitForTimeout(1600);

  await page.screencast.stop();
}
