'use strict';
// Resolve only the operation target. Captured DOM marker values are never rewritten.
function workflowStudentId(marker, address, base) {
  if (/^[1-9][0-9]*$/.test(marker || '')) return { id: marker, source: 'visible-marker' };
  try {
    const url = new URL(address), origin = new URL(base);
    const match = /^\/Student\/Details\/([1-9][0-9]*)$/.exec(url.pathname);
    if (url.origin === origin.origin && !url.username && !url.password && !url.search && !url.hash && match)
      return { id: match[1], source: 'observed-details-url' };
  } catch (_) {}
  return { id: null, source: 'unresolved' };
}
module.exports = { workflowStudentId };
