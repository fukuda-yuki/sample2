/* Real browser collector. Reads live DOM only; never repairs application JS,
 * sends removal HTTP directly, or reloads/navigates after the removal click. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = process.argv[3];
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const write = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const ref = name => ({ path: name, sha256: sha(fs.readFileSync(path.join(out, name))) });
const conditions = {
  collectorVersion: '1.0.1', collectorSha256: sha(fs.readFileSync(__filename)),
  playwrightVersion: require('playwright/package.json').version, nodeVersion: process.version,
  browser: 'chromium', headless: true, viewport: { width: 1280, height: 900 },
  locale: 'en-US', timezoneId: 'UTC', actionTimeoutMs: 5000, navigationTimeoutMs: 15000,
  updateTimeoutMs: 10000, stableExpectedMs: 500, pollMs: 200,
  sessionPolicy: 'fresh browser context per check; independently populate 2 and 1',
  networkPolicy: 'normal browser subresource loading; no request-routing overrides; external script identity recorded',
  observation: 'visible cart DOM and PNG in the clicked page; no post-click navigation or reload',
};

// Read-only projection excludes rows hidden by the application's own UI updates.
async function observe(page) {
  return page.evaluate(() => {
    const visible = e => !!(e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden';
    const rows = [...document.querySelectorAll('tr[id^="row-"]')].filter(visible);
    const totals = [...document.querySelectorAll('[id="cart-total"]')].filter(visible);
    return {
      html: document.documentElement.outerHTML, url: location.href,
      visibleCartHtml: '<table>' + rows.map(e => e.outerHTML).join('') + '<tr>' + totals.map(e => e.outerHTML).join('') + '</tr></table>',
      rows: rows.map(e => ({ id: e.id, count: e.querySelector('[id="item-count-' + e.id.slice(4) + '"]')?.textContent.trim(),
        album: [...e.querySelectorAll('a[href]')].map(a => new URL(a.href).pathname).find(p => /^\/Store\/Details\/\d+\/?$/i.test(p)) })),
      totals: totals.map(e => e.textContent.trim()),
    };
  });
}
function matches(state, quantity) {
  return state.totals.length === 1 && state.totals[0] === (input.price * quantity).toFixed(2)
    && (quantity === 0 ? state.rows.length === 0 : state.rows.length === 1
      && state.rows[0].count === String(quantity) && state.rows[0].album.replace(/\/$/, '') === '/Store/Details/' + input.albumId);
}
async function capture(page, tabId, name) {
  const state = await observe(page);
  write(name + '.json', { at: new Date().toISOString(), tabId, page: state });
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true, timeout: 5000 });
  return { dom: ref(name + '.json'), screenshot: ref(name + '.png'), state };
}

(async () => {
  let browser;
  const receipt = { schemaVersion: 1, actor: 'agent', runInstanceId: input.runInstanceId,
    artifactSha256: input.artifactSha256, specSha256: input.specSha256, conditions, removals: [] };
  try {
    const executablePath = process.env.SAMPLE2_BROWSER_EXECUTABLE || chromium.executablePath();
    conditions.executablePath = executablePath;
    conditions.executableSha256 = sha(fs.readFileSync(executablePath));
    browser = await chromium.launch({ headless: true, executablePath, timeout: 15000 });
    conditions.browserVersion = browser.version();
    for (const [checkId, count] of [['C-015', 2], ['C-016', 1]]) {
      const context = await browser.newContext({ viewport: conditions.viewport, locale: conditions.locale,
        timezoneId: conditions.timezoneId, serviceWorkers: 'block', acceptDownloads: false });
      const tabId = crypto.randomUUID(), events = [], pending = new Set(), resourceReads = [], externalScriptFaults = [];
      const record = (kind, data) => events.push({ at: new Date().toISOString(), kind, ...data });
      const page = await context.newPage();
      page.setDefaultTimeout(conditions.actionTimeoutMs);
      page.setDefaultNavigationTimeout(conditions.navigationTimeoutMs);
      page.on('request', r => { pending.add(r); record('request', { method: r.method(), url: r.url() }); });
      page.on('requestfinished', r => pending.delete(r));
      page.on('requestfailed', r => {
        pending.delete(r); record('requestfailed', { url: r.url(), error: r.failure() });
        if (r.resourceType() === 'script' && new URL(r.url()).origin !== new URL(input.baseUrl).origin)
          externalScriptFaults.push({ url: r.url(), error: r.failure() });
      });
      page.on('response', r => {
        record('response', { status: r.status(), url: r.url() });
        if (r.request().resourceType() === 'script' && new URL(r.url()).origin !== new URL(input.baseUrl).origin) {
          resourceReads.push((async () => {
            try {
              const body = await r.body();
              record('external-script', { url: r.url(), status: r.status(), sha256: sha(body), bytes: body.length });
              if (!r.ok()) externalScriptFaults.push({ url: r.url(), status: r.status() });
            } catch (e) { externalScriptFaults.push({ url: r.url(), error: String(e) }); }
          })());
        }
      });
      page.on('console', m => record('console', { type: m.type(), text: m.text() }));
      page.on('pageerror', e => record('pageerror', { message: e.message }));
      await context.tracing.start({ screenshots: true, snapshots: true });
      try {
        await page.goto(input.baseUrl + '/ShoppingCart', { waitUntil: 'load' });
        if (!matches(await observe(page), 0)) throw new Error(checkId + ': empty-session precondition not established');
        // Public AddToCart route is used only for preparation, before observation/click.
        for (let n = 0; n < count; n++)
          await page.goto(input.baseUrl + '/ShoppingCart/AddToCart/' + input.albumId, { waitUntil: 'load' });
        const before = await capture(page, tabId, checkId + '-before');
        await Promise.all(resourceReads);
        if (externalScriptFaults.length) throw new Error(checkId + ': external script observation incomplete: ' + JSON.stringify(externalScriptFaults));
        if (!matches(before.state, count)) throw new Error(checkId + ': populated precondition not established');
        const row = page.locator('tr[id="' + before.state.rows[0].id + '"]');
        // Public CSS identifier, semantic link/button name or form action; no implementation/Run-specific branch.
        const control = row.locator('.RemoveLink:visible, a[href*="RemoveFromCart"]:visible, form[action*="RemoveFromCart"] button:visible, form[action*="RemoveFromCart"] input[type="submit"]:visible')
          .or(row.getByRole('link', { name: /remove|delete|削除/i })).or(row.getByRole('button', { name: /remove|delete|削除/i }));
        if (await control.count() !== 1) throw new Error(checkId + ': removal control is missing or ambiguous');
        const clickedAt = new Date().toISOString(), start = performance.now();
        record('ui-click-remove', { selector: before.state.rows[0].id });
        await control.click({ timeout: conditions.actionTimeoutMs, noWaitAfter: true });
        let stableSince = null, completion = 'update_deadline';
        while (performance.now() - start < conditions.updateTimeoutMs) {
          try {
            const current = await observe(page);
            if (matches(current, count - 1) && pending.size === 0) {
              stableSince ??= performance.now();
              if (performance.now() - stableSince >= conditions.stableExpectedMs) { completion = 'expected_state_stable'; break; }
            } else stableSince = null;
          } catch (e) {
            if (!String(e).includes('Execution context was destroyed')) throw e;
            stableSince = null; // normal application navigation; keep waiting on this page
          }
          await sleep(conditions.pollMs);
        }
        const after = await capture(page, tabId, checkId + '-after');
        await Promise.all(resourceReads);
        if (externalScriptFaults.length) throw new Error(checkId + ': external script observation incomplete: ' + JSON.stringify(externalScriptFaults));
        receipt.removals.push({ checkId, action: 'click-remove', before: before.dom, after: after.dom,
          beforeScreenshot: before.screenshot, afterScreenshot: after.screenshot,
          clickedAt, elapsedMs: Math.round(performance.now() - start), completion, pendingRequests: pending.size });
      } finally {
        write(checkId + '-events.json', events);
        await context.tracing.stop({ path: path.join(out, checkId + '-trace.zip') });
        await context.close();
      }
    }
    write('receipt.json', receipt);
    write('collector-result.json', { status: 'observed', conditions, checks: receipt.removals.map(r => r.checkId) });
  } catch (e) {
    write('collector-result.json', { status: 'evaluator_fault', conditions, message: String(e.stack || e), completedChecks: receipt.removals.map(r => r.checkId) });
    process.exitCode = 2;
  } finally { if (browser) await browser.close(); }
})();
