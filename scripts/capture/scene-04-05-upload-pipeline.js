// Scenes 4 and 5, shot in one pass against a LIVE pipeline run.
//
// They have to share a run: scene 5 is the real transcribe/analyze pipeline
// kicked off by scene 4's upload, and splitting them into two `run-code` calls
// would drop a few seconds of dead gap between the takes. Two screencast files
// come out of one script.
//
// Real speed throughout. Do not ramp here - Remotion does that with
// playbackRate on scene 5.
//
//   playwright-cli run-code --filename=scripts/capture/scene-04-05-upload-pipeline.js

async page => {
  const APP = 'http://localhost:3000';
  const API = 'http://localhost:8000/api';
  const FIXTURE = 'tests/fixtures/demo/demo_seminar.mp3';
  const INSTRUCTION = 'Find every income claim, then cut the filler words and dead air';

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

  // ---------------------------------------------------------------- scene 4
  await page.goto(APP);
  await page.waitForTimeout(1500);

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-04-upload.webm',
    size: { width: 1440, height: 900 },
  });
  await page.waitForTimeout(1200);

  const prompt = page.locator('#prompt');
  let r = await ring(prompt);
  await prompt.click();
  await prompt.pressSequentially(INSTRUCTION, { delay: 60 });
  await page.waitForTimeout(1100);
  await r.dispose();

  // The preset beat. A native <select> popup is drawn by the OS and never lands
  // in a CDP screencast, so we show the presets by their *effect*: pick one,
  // let the viewer watch the instruction box grey out and the rulebook take
  // over, then hand control back to the typed instruction.
  const preset = page.locator('#preset');
  r = await ring(preset);
  await page.waitForTimeout(600);
  await preset.selectOption('income-claims');
  await page.waitForTimeout(2200);
  await preset.selectOption('');
  await page.waitForTimeout(700);
  await r.dispose();

  await prompt.click();
  await prompt.pressSequentially(INSTRUCTION, { delay: 45 });
  await page.waitForTimeout(900);

  const scrubber = page.getByRole('checkbox', { name: 'Scrubber mode' });
  r = await ring(scrubber, 6);
  await page.waitForTimeout(500);
  await scrubber.check();
  await page.waitForTimeout(800);
  await r.dispose();

  const dropzone = page.getByText('Drop media files here');
  r = await ring(dropzone, 18);
  await page.waitForTimeout(900);
  await page.setInputFiles('#file-input', FIXTURE);
  await page.waitForTimeout(600);
  await r.dispose();

  await page.getByText('Recent Projects').waitFor({ timeout: 30000 });
  await page.waitForTimeout(2000);
  await page.screencast.stop();

  // ---------------------------------------------------------------- scene 5
  // Nothing on the home screen opens a job that is still processing, so find
  // the job we just created and go straight to it.
  const jobId = await page.evaluate(async api => {
    const jobs = await (await fetch(`${api}/jobs`)).json();
    const active = jobs.find(j => !['completed', 'failed'].includes(j.status));
    return (active || jobs[0]).id;
  }, API);

  await page.goto(`${APP}/jobs/${jobId}`);
  await page.getByText('This page updates on its own. You can leave it open.')
    .waitFor({ timeout: 30000 });

  await page.screencast.start({
    path: 'docs/demo/captures/raw/scene-05-pipeline.webm',
    size: { width: 1440, height: 900 },
  });

  // Real time. Transcribing runs ~28s on a 70-90s clip, analyze 3-4s,
  // export a couple more because Scrubber mode is on.
  await page.getByText(/^Suggested Edits \(\d+\)$/).waitFor({ timeout: 300000 });
  await page.waitForTimeout(2500);
  await page.screencast.stop();

  return { jobId };
}
