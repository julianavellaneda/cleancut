// Scene 8 - export, download, play the result. Seed first:
//   python scripts/seed_demo_job.py --state cleaned
//   playwright-cli run-code --filename=scripts/capture/scene-08-export.js
//
// 'cleaned' matters: Export Edited stays disabled until at least one violation
// is accepted.

async page => {
  const JOB = 'demo-0000-0000-0000-cleancut';

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

  // Download Master calls window.open(). A popup backgrounds this tab and CDP
  // stops emitting screencast frames mid-scene, so close it the moment it opens.
  page.context().on('page', p => p.close().catch(() => {}));

  await page.goto(`http://localhost:3000/jobs/${JOB}`);
  await page.getByText(/^Suggested Edits \(\d+\)$/).waitFor();
  await page.waitForTimeout(2500);

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-08-export.webm',
    size: { width: 1440, height: 900 },
  });
  await page.waitForTimeout(1600);

  const exportBtn = page.getByRole('button', { name: 'Export Edited' });
  let r = await ring(exportBtn, 8);
  await page.waitForTimeout(900);
  await exportBtn.click();
  await page.waitForTimeout(1200);                       // 'Exporting...'
  await r.dispose();

  const download = page.getByRole('button', { name: 'Download Master' });
  await download.waitFor({ timeout: 180000 });
  await page.waitForTimeout(1400);

  r = await ring(download, 8);
  await page.waitForTimeout(900);
  await download.click();
  await page.waitForTimeout(1500);
  await r.dispose();

  // The result plays in the page - shorter than the source, edits applied.
  const player = page.locator('main audio, main video').last();
  await player.scrollIntoViewIfNeeded();
  await page.waitForTimeout(900);
  r = await ring(player, 10);
  await page.waitForTimeout(800);
  await player.evaluate(el => el.play());
  await r.dispose();
  await page.waitForTimeout(9000);                       // let the progress bar travel

  await page.screencast.stop();
}
