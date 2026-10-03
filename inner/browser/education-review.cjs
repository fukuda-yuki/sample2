'use strict';
// Visible ordinary form controls only. Never repair application code, POST
// directly or force navigation after Save to manufacture the saved state.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const { chromium } = require('playwright');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), out = process.argv[3];
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const ref = name => ({ path: name, sha256: sha(fs.readFileSync(path.join(out, name))) });
const write = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const receipt = { schemaVersion: 1, actor: 'agent', runInstanceId: input.runInstanceId,
  artifactSha256: input.artifactSha256, specSha256: input.specSha256,
  action: 'not-run-unsupported', faults: [], conditions: {
    collectorVersion: 'education-1.0.0', collectorSha256: sha(fs.readFileSync(__filename)),
    nodeVersion: process.version, playwrightVersion: require('playwright/package.json').version,
    viewport: { width: 1280, height: 900 }, locale: 'en-US', timezoneId: 'UTC',
    observation: 'Actual Create then Edit/Save with normal application navigation; no forced post-Save navigation',
    actionTimeoutMs: 5000, updateTimeoutMs: 10000,
  } };
async function capture(page, name, tabId) {
  const state = await page.evaluate(() => {
    const marker = id => {
      const els = [...document.querySelectorAll('[id="' + id + '"]')]
        .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
      return els.length === 1 ? els[0].textContent.trim() : null;
    };
    return { html: document.documentElement.outerHTML, url: location.href,
      studentId: marker('student-id'), firstName: marker('student-first-name'),
      lastName: marker('student-last-name'), enrollmentDate: marker('student-enrollment-date'),
      fullName: marker('student-full-name') };
  });
  write(name + '.json', { at: new Date().toISOString(), tabId, page: state });
  await page.screenshot({ path: path.join(out, name + '.png'), fullPage: true, timeout: 5000 });
  return state;
}
async function formSupported(page, name) {
  for (const field of ['LastName', 'FirstMidName', 'EnrollmentDate'])
    if (await page.locator('[name="' + field + '"]:visible').count() !== 1) return false;
  const button = page.getByRole('button', { name, exact: true });
  return await button.count() === 1 && await button.isEnabled();
}
async function fill(page, fields) {
  for (const [name, value] of Object.entries(fields)) await page.locator('[name="' + name + '"]:visible').fill(value);
}
(async () => {
  let browser, context;
  const events = [], tabId = crypto.randomUUID(), resourceReads = [], externalScriptFaults = [];
  try {
    const executablePath = process.env.SAMPLE2_BROWSER_EXECUTABLE || chromium.executablePath();
    receipt.conditions.executablePath = executablePath;
    receipt.conditions.executableSha256 = sha(fs.readFileSync(executablePath));
    browser = await chromium.launch({ executablePath, headless: true });
    receipt.conditions.browserVersion = browser.version();
    context = await browser.newContext({ viewport: receipt.conditions.viewport,
      locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block', acceptDownloads: false });
    const page = await context.newPage();
    page.setDefaultTimeout(5000); page.setDefaultNavigationTimeout(15000);
    page.on('request', r => events.push({ at: new Date().toISOString(), kind: 'request', method: r.method(), url: r.url() }));
    page.on('requestfailed', r => {
      events.push({ at: new Date().toISOString(), kind: 'requestfailed', url: r.url(), error: r.failure() });
      if (r.resourceType() === 'script' && new URL(r.url()).origin !== new URL(input.baseUrl).origin)
        externalScriptFaults.push({ url: r.url(), error: r.failure() });
    });
    page.on('response', r => {
      events.push({ at: new Date().toISOString(), kind: 'response', status: r.status(), url: r.url() });
      if (r.request().resourceType() === 'script' && new URL(r.url()).origin !== new URL(input.baseUrl).origin)
        resourceReads.push((async () => {
          try {
            const body = await r.body();
            events.push({ at: new Date().toISOString(), kind: 'external-script', url: r.url(), status: r.status(), sha256: sha(body), bytes: body.length });
            if (!r.ok()) externalScriptFaults.push({ url: r.url(), status: r.status() });
          } catch (e) { externalScriptFaults.push({ url: r.url(), error: String(e) }); }
        })());
    });
    page.on('pageerror', e => events.push({ at: new Date().toISOString(), kind: 'pageerror', message: String(e) }));
    await context.tracing.start({ screenshots: true, snapshots: true });
    await page.goto(input.baseUrl + '/Student/Create', { waitUntil: 'load' });
    await capture(page, 'before', tabId);
    receipt.before = ref('before.json'); receipt.beforeScreenshot = ref('before.png');
    if (!await formSupported(page, 'Create')) { receipt.reason = 'ordinary_create_form_unsupported'; return; }
    await fill(page, input.createFields);
    await page.getByRole('button', { name: 'Create', exact: true }).click({ noWaitAfter: true });
    events.push({ at: new Date().toISOString(), kind: 'ui-click-create' });
    try { await page.waitForURL(/\/Student\/Details\/\d+\/?$/, { timeout: 10000, waitUntil: 'load' }); } catch (_) {}
    const created = await capture(page, 'created', tabId); receipt.created = ref('created.json');
    if (!/^\d+$/.test(created.studentId || '')) {
      receipt.action = 'create-not-completed'; receipt.reason = 'details_identifier_not_observed_after_create';
      await capture(page, 'after', tabId); receipt.after = ref('after.json'); receipt.afterScreenshot = ref('after.png'); return;
    }
    receipt.studentId = created.studentId;
    // Setup navigation before the measured Save action is explicit in evidence.
    await page.goto(input.baseUrl + '/Student/Edit/' + created.studentId, { waitUntil: 'load' });
    await capture(page, 'edit', tabId); receipt.edit = ref('edit.json');
    if (!await formSupported(page, 'Save')) { receipt.reason = 'ordinary_save_form_unsupported'; return; }
    await fill(page, input.editFields);
    await page.getByRole('button', { name: 'Save', exact: true }).click({ noWaitAfter: true });
    events.push({ at: new Date().toISOString(), kind: 'ui-click-save', studentId: created.studentId });
    receipt.action = 'create-edit-save';
    try { await page.waitForURL(url => url.pathname.replace(/\/$/, '') === '/Student/Details/' + created.studentId,
      { timeout: 10000, waitUntil: 'load' }); } catch (_) {}
    await capture(page, 'after', tabId); receipt.after = ref('after.json'); receipt.afterScreenshot = ref('after.png');
  } catch (e) { receipt.faults.push(String(e.stack || e)); process.exitCode = 2; }
  finally {
    await Promise.all(resourceReads);
    if (externalScriptFaults.length) {
      receipt.faults.push('External script observation incomplete: ' + JSON.stringify(externalScriptFaults));
      process.exitCode = 2;
    }
    if (context) { try { await context.tracing.stop({ path: path.join(out, 'trace.zip') }); } catch (e) { receipt.faults.push(String(e)); } }
    if (browser) { try { await browser.close(); } catch (e) { receipt.faults.push(String(e)); } }
    write('events.json', events); write('collector-receipt.json', receipt);
  }
})();
