// Reference copy of the highlight-ring helper. Each scene file inlines its own
// copy so it stays runnable standalone via `playwright-cli run-code --filename=...`
// (run-code evaluates a bare `async page => {}` expression; there is no module
// scope to import from). Edit here first, then propagate.
//
// Sticky-overlay form on purpose: showOverlay(html, {duration}) hands back timing
// control to the overlay, and we want the ring visibly up *during* the click.

const ring = async (page, locator, pad = 8) => {
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

// Usage:
//   const r = await ring(page, page.locator('#prompt'));
//   await page.waitForTimeout(700);
//   await page.locator('#prompt').click();
//   await page.waitForTimeout(400);
//   await r.dispose();
