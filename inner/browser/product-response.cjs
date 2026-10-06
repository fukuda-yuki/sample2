'use strict';
// An observed response is a product fact only for the measured owned operation.
function productResponse(baseUrl, operation, actual) {
  if (!operation || !actual || !Number.isInteger(actual.status) || actual.status < 500 || actual.status > 599) return null;
  let target, base;
  try { target = new URL(actual.url); base = new URL(baseUrl); } catch (_) { return null; }
  if (base.protocol !== 'http:' || !['127.0.0.1', '[::1]'].includes(base.hostname)
      || !base.port || target.origin !== base.origin || target.pathname !== operation.path
      || target.search || actual.method !== operation.method
      || !['document', 'xhr', 'fetch'].includes(actual.resourceType)) return null;
  return { caseId: operation.caseId, checkId: operation.checkId, operation: operation.operation,
    method: actual.method, url: actual.url, status: actual.status,
    clickConfirmed: !!operation.clickConfirmed };
}
function recorder(page, input, receipt, write, ref, sha) {
  let current = null, sequence = 0;
  let written = 0;
  const requests = new WeakMap(), reads = [];
  page.on('request', request => requests.set(request, current));
  page.on('response', response => {
    const request = response.request(), operation = requests.get(request);
    if (!operation) return;
    const actual = { method: request.method(), url: response.url(), status: response.status(), resourceType: request.resourceType() };
    const failure = productResponse(input.baseUrl, operation, actual);
    if (!failure) return;
    const name = 'product-response-' + (++sequence) + '-' + operation.caseId + '.json';
    reads.push((async () => {
      const evidence = { ...failure, resourceType: actual.resourceType, requestPayload: request.postData() };
      try {
        const body = await response.body();
        evidence.responseBody = body.toString('utf8'); evidence.responseBodySha256 = sha(body); evidence.responseBytes = body.length;
      } catch (error) {
        evidence.bodyReadError = String(error);
        receipt.faults.push('Response body observation incomplete: ' + String(error));
      }
      return { name, evidence, failure, operation };
    })());
  });
  return { set: operation => { current = operation; },
    confirm: caseId => { if (current?.caseId === caseId) current.clickConfirmed = true; },
    flush: async () => {
      const batch = await Promise.all(reads);
      for (; written < batch.length; written++) {
        const { name, evidence, failure, operation } = batch[written];
        evidence.clickConfirmed = failure.clickConfirmed = !!operation.clickConfirmed;
        write(name, evidence); receipt.productFailures.push({ ...failure, evidence: ref(name) });
      }
    },
    failed: caseId => receipt.productFailures.some(value => value.caseId === caseId) };
}
module.exports = { productResponse, recorder };
