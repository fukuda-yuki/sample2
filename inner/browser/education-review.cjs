'use strict';
// Visible ordinary form controls only. Never repair application code, POST
// directly or force navigation after Save to manufacture the saved state.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const { chromium } = require('playwright');
const { workflowStudentId } = require('./education-identity.cjs');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), out = process.argv[3];
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const ref = name => ({ path: name, sha256: sha(fs.readFileSync(path.join(out, name))) });
const write = (name, value) => fs.writeFileSync(path.join(out, name), JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
const repaired = input.evaluationVersion === 'education-1.1.0';
const recorder = repaired ? require('./product-response.cjs').recorder : null;
const receipt = { schemaVersion: repaired ? 2 : 1, actor: 'agent', runInstanceId: input.runInstanceId,
  artifactSha256: input.artifactSha256, specSha256: input.specSha256,
  action: 'not-run-unsupported', faults: [], conditions: {
    collectorVersion: repaired ? 'education-1.1.0' : 'education-1.0.0', collectorSha256: sha(fs.readFileSync(__filename)),
    nodeVersion: process.version, playwrightVersion: require('playwright/package.json').version,
    viewport: { width: 1280, height: 900 }, locale: 'en-US', timezoneId: 'UTC',
    observation: 'Actual Create then Edit/Save with normal application navigation; no forced post-Save navigation',
    actionTimeoutMs: 5000, updateTimeoutMs: 10000,
  } };
if (repaired) Object.assign(receipt, { baseUrl: input.baseUrl, evaluationVersion: input.evaluationVersion,
  requestSha256: sha(fs.readFileSync(process.argv[2])), productFailures: [] });
if (repaired) receipt.conditions.productResponseHelperSha256 = sha(fs.readFileSync(path.join(__dirname, 'product-response.cjs')));
async function capture(page, name, tabId) {
  const state = await page.evaluate(repaired => {
    const marker = id => {
      const els = [...document.querySelectorAll('[id="' + id + '"]')]
        .filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
      return els.length === 1 ? els[0].textContent.trim() : null;
    };
    if (!repaired) return { html: document.documentElement.outerHTML, url: location.href,
      studentId: marker('student-id'), firstName: marker('student-first-name'),
      lastName: marker('student-last-name'), enrollmentDate: marker('student-enrollment-date'),
      fullName: marker('student-full-name') };
    const target = /^\/Student\/Details\/([1-9][0-9]*)$/.exec(location.pathname)?.[1];
    const visible = e => {
      for (let n = e; n; n = n.parentElement) {
        const style = getComputedStyle(n);
        if (['SCRIPT','STYLE','TEMPLATE','NOSCRIPT'].includes(n.tagName) || n.hidden ||
            style.display === 'none' || ['hidden','collapse'].includes(style.visibility) || Number(style.opacity) === 0) return false;
      }
      if (e.getClientRects().length) return true;
      // A display:contents marker has no box of its own; its text can render.
      if (getComputedStyle(e).display !== 'contents') return false;
      const range = document.createRange(); range.selectNodeContents(e);
      return !!range.getClientRects().length;
    };
    const text = node => {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (node.nodeType === Node.ELEMENT_NODE && !visible(node)) return '';
      return [...node.childNodes].map(text).join('');
    };
    const read = name => {
      const nodes = [...document.querySelectorAll('[id="'+name+'"],['+name+']')];
      if (!nodes.length) return { status: 'invalid', value: null };
      if (nodes.length !== 1) return { status: 'unresolved', value: null };
      const node = nodes[0];
      for (let e = node; e; e = e.parentElement)
        if (target && e.getAttribute('student-id') && e.getAttribute('student-id') !== target) return { status: 'invalid', value: null };
      const value = text(node).trim(), attribute = node.getAttribute(name);
      if (!visible(node) && name !== 'student-id') return { status: 'invalid', value: null };
      if (attribute && attribute !== value) {
        const compound = [...node.attributes].filter(a => /^(student-|course-)/.test(a.name) || a.name === 'department-name').length > 1;
        if ((name === 'student-id' && (!value || compound)) || (compound && value.includes(attribute)))
          return { status: 'unresolved', value: attribute };
        return { status: 'invalid', value: null };
      }
      return { status: 'observed', value };
    };
    const fields = { studentId: 'student-id', firstName: 'student-first-name', lastName: 'student-last-name',
      enrollmentDate: 'student-enrollment-date', fullName: 'student-full-name' };
    const state = { html: document.documentElement.outerHTML, url: location.href, markerObservations: {} };
    for (const [field, name] of Object.entries(fields)) {
      const reading = read(name); state.markerObservations[name] = reading;
      state[field] = reading.status === 'observed' ? reading.value : null;
    }
    return state;
  }, repaired);
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
  let browser, context, responses;
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
    if (repaired) responses = recorder(page, input, receipt, write, ref, sha);
    let activeCase = 'browser-launch'; const requestCases = new WeakMap();
    function operation(caseId, method, route, clicked = false) {
      activeCase = caseId;
      if (responses) responses.set({ caseId, checkId: 'E-012', operation: 'school-' + caseId,
        method, path: route, clickConfirmed: clicked });
    }
    async function navigate(caseId, route) {
      operation(caseId, 'GET', route);
      try { await page.goto(input.baseUrl + route, { waitUntil: 'load' }); }
      catch (error) {
        if (responses) await responses.flush();
        if (!(responses?.failed(caseId) && String(error).includes('net::ERR_HTTP_RESPONSE_CODE_FAILURE'))) throw error;
      }
      if (responses) await responses.flush();
      if (responses?.failed(caseId)) { receipt.action = 'product-http-failed'; return false; }
      return true;
    }
    page.setDefaultTimeout(5000); page.setDefaultNavigationTimeout(15000);
    page.on('request', r => {
      requestCases.set(r, activeCase);
      events.push({ at: new Date().toISOString(), kind: 'request', caseId: activeCase, method: r.method(), url: r.url(), requestPayload: r.postData() });
    });
    page.on('requestfailed', r => {
      events.push({ at: new Date().toISOString(), kind: 'requestfailed', url: r.url(), error: r.failure() });
      if (r.resourceType() === 'script' && new URL(r.url()).origin !== new URL(input.baseUrl).origin)
        externalScriptFaults.push({ url: r.url(), error: r.failure() });
    });
    page.on('response', r => {
      events.push({ at: new Date().toISOString(), kind: 'response', caseId: requestCases.get(r.request()), method: r.request().method(), status: r.status(), url: r.url() });
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
    if (!await navigate('create-form', '/Student/Create')) return;
    await capture(page, 'before', tabId);
    receipt.before = ref('before.json'); receipt.beforeScreenshot = ref('before.png');
    if (!await formSupported(page, 'Create')) { receipt.reason = 'ordinary_create_form_unsupported'; return; }
    await fill(page, input.createFields);
    operation('create-submit', 'POST', '/Student/Create');
    await page.getByRole('button', { name: 'Create', exact: true }).click({ noWaitAfter: true });
    responses?.confirm('create-submit');
    events.push({ at: new Date().toISOString(), kind: 'ui-click-create' });
    try { await page.waitForURL(/\/Student\/Details\/\d+\/?$/, { timeout: 10000, waitUntil: 'load' }); } catch (_) {}
    if (responses) await responses.flush();
    if (responses?.failed('create-submit')) { receipt.action = 'product-http-failed'; return; }
    const created = await capture(page, 'created', tabId); receipt.created = ref('created.json');
    const identity = workflowStudentId(created.studentId, created.url, input.baseUrl);
    const createdId = identity.id;
    receipt.studentIdentifierSource = identity.source;
    receipt.conditions.identityHelperSha256 = sha(fs.readFileSync(path.join(__dirname, 'education-identity.cjs')));
    if (!createdId) {
      receipt.action = 'create-not-completed'; receipt.reason = 'details_identifier_not_observed_after_create';
      await capture(page, 'after', tabId); receipt.after = ref('after.json'); receipt.afterScreenshot = ref('after.png'); return;
    }
    receipt.studentId = createdId;
    // Setup navigation before the measured Save action is explicit in evidence.
    if (!await navigate('edit-form', '/Student/Edit/' + createdId)) return;
    await capture(page, 'edit', tabId); receipt.edit = ref('edit.json');
    if (!await formSupported(page, 'Save')) { receipt.reason = 'ordinary_save_form_unsupported'; return; }
    await fill(page, input.editFields);
    operation('edit-submit', 'POST', '/Student/Edit/' + createdId);
    await page.getByRole('button', { name: 'Save', exact: true }).click({ noWaitAfter: true });
    responses?.confirm('edit-submit');
    events.push({ at: new Date().toISOString(), kind: 'ui-click-save', studentId: createdId });
    receipt.action = 'create-edit-save';
    try { await page.waitForURL(url => url.pathname.replace(/\/$/, '') === '/Student/Details/' + createdId,
      { timeout: 10000, waitUntil: 'load' }); } catch (_) {}
    if (responses) await responses.flush();
    if (responses?.failed('edit-submit')) { receipt.action = 'product-http-failed'; return; }
    await capture(page, 'after', tabId); receipt.after = ref('after.json'); receipt.afterScreenshot = ref('after.png');
  } catch (e) { receipt.faults.push(String(e.stack || e)); process.exitCode = 2; }
  finally {
    if (responses) { try { await responses.flush(); } catch (e) { receipt.faults.push(String(e)); } }
    await Promise.all(resourceReads);
    if (externalScriptFaults.length) {
      receipt.faults.push('External script observation incomplete: ' + JSON.stringify(externalScriptFaults));
      process.exitCode = 2;
    }
    if (context) { try { await context.tracing.stop({ path: path.join(out, 'trace.zip') }); } catch (e) { receipt.faults.push(String(e)); } }
    if (browser) { try { await browser.close(); } catch (e) { receipt.faults.push(String(e)); } }
    if (receipt.faults.length) process.exitCode = 2;
    write('events.json', events); write('collector-receipt.json', receipt);
  }
})();
